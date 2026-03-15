"""Recommendation API endpoints — Phase 3.5 (persistent).

This module is the "glue" between the frontend and the recommendation
engine.  Phase 3.5 upgrades it from in-memory caching to full database
persistence.

What changed from Phase 3
─────────────────────────
Phase 3 used two Python dicts:
  ``_recommendation_cache``  — lost on server restart
  ``_feedback_store``        — lost on server restart

Phase 3.5 replaces both with database tables:
  ``RecommendationSession`` + ``RecommendationEntry``  — survive restarts
  ``RecommendationFeedback``                           — survive restarts

This means:
• Users see their last recommendations when they come back
• Feedback persists and influences future recommendations
• We can show recommendation history ("what did it suggest yesterday?")

Endpoint design
───────────────
• POST /generate — expensive (calls LLM, ~3-5 seconds, costs money).
  Now saves the session + entries to the database.

• GET / — cheap (reads from DB).  Returns the most recent session.
  Survives server restarts.

• GET /history — returns past recommendation sessions (lightweight).
  Frontend renders a history sidebar.

• GET /{session_id} — load a specific past session's recommendations.

• POST /feedback — records user feedback AND applies preference tuning.
  Persists to DB and adjusts the user's preference profile.

• GET /feedback — returns the user's feedback map so the frontend
  can show which recs they already rated (survives page reload).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.logging import logger
from app.models.anime import AnimeEntry, AnimeList, UserPreferenceProfile
from app.models.recommendation import (
    RecommendationEntry,
    RecommendationFeedback,
    RecommendationSession,
)
from app.models.user import User
from app.schemas.recommendation import (
    RecommendationFeedbackRequest,
    RecommendationFeedbackResponse,
    RecommendationHistoryResponse,
    RecommendationItem,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationSessionSummary,
    UserFeedbackMapResponse,
)
from app.services.preference_analyzer import apply_feedback_adjustments
from app.services.recommender import generate_recommendations

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


# ═════════════════════════════════════════════════════════
# POST /api/recommendations/generate
# ═════════════════════════════════════════════════════════


@router.post("/generate", response_model=RecommendationResponse)
def generate_recs(
    body: RecommendationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate fresh anime recommendations for the current user.

    This is the expensive endpoint — it calls the vector store and
    the LLM.  Takes ~3-5 seconds and costs ~$0.001-0.003 per call.

    Phase 3.5 changes:
    ───────────────────
    1. Loads feedback adjustments and applies them to the preference
       profile before generating (so feedback influences results).
    2. Saves the session + entries to the database (replaces in-memory
       cache).  Recommendations now survive server restarts.
    3. Passes disliked/watched feedback MAL IDs to the retriever so
       they're excluded from candidates.

    Prerequisites:
    - User must be logged in
    - User must have imported their MAL list (preference profile exists)
    """
    # ── Check prerequisites ──────────────────────────────
    profile = db.execute(
        select(UserPreferenceProfile).where(
            UserPreferenceProfile.user_id == user.id
        )
    ).scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=404,
            detail=(
                "No preference profile found. "
                "Import your MAL list first via POST /api/mal/import."
            ),
        )

    # ── Apply feedback adjustments to the profile ────────
    # This is the key Phase 3.5 addition: feedback from previous
    # sessions modifies the preference profile so the retriever
    # and LLM produce better results over time.
    feedbacks = db.execute(
        select(RecommendationFeedback).where(
            RecommendationFeedback.user_id == user.id
        )
    ).scalars().all()

    adjusted_profile = apply_feedback_adjustments(
        profile.profile_data, feedbacks
    )

    # ── Get watched anime IDs (to exclude from recommendations) ──
    watched_mal_ids = _get_watched_mal_ids(user.id, db)

    # ── Also exclude disliked + "watched" feedback anime ─
    # "disliked" → user explicitly said "not for me"
    # "watched" → user said they already watched it (not on MAL list)
    feedback_exclude_ids = _get_feedback_exclude_ids(user.id, db)
    all_exclude_ids = watched_mal_ids | feedback_exclude_ids

    # ── Generate recommendations ─────────────────────────
    try:
        raw_recommendations = generate_recommendations(
            preference_profile=adjusted_profile,
            watched_mal_ids=all_exclude_ids,
            num_recommendations=body.num_recommendations,
            custom_query=body.custom_query,
        )
    except ValueError as e:
        # No candidates found (empty vector store)
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        # OpenAI API key not configured
        raise HTTPException(status_code=500, detail=str(e))

    # ── Persist to database ──────────────────────────────
    # This is the big Phase 3.5 change: instead of storing in a
    # Python dict, we create database rows.  This means:
    # • Recommendations survive server restarts
    # • We can show history of past sessions
    # • We have an audit trail of what was recommended
    used_fallback = any(
        rec.get("is_fallback", False) for rec in raw_recommendations
    )

    session_record = RecommendationSession(
        user_id=user.id,
        custom_query=body.custom_query,
        used_fallback=used_fallback,
        total_count=len(raw_recommendations),
    )
    db.add(session_record)
    db.flush()  # Ensure session_record.id is available for entries

    # Create an entry for each recommendation
    for rec in raw_recommendations:
        entry = RecommendationEntry(
            session_id=session_record.id,
            mal_id=rec.get("mal_id", 0),
            title=rec.get("title", "Unknown"),
            image_url=rec.get("image_url"),
            genres=rec.get("genres", ""),
            themes=rec.get("themes", ""),
            synopsis=rec.get("synopsis", ""),
            mal_score=rec.get("mal_score"),
            year=rec.get("year"),
            anime_type=rec.get("anime_type"),
            reasoning=rec.get("reasoning", "No reasoning provided."),
            confidence=rec.get("confidence", "medium"),
            similar_to=rec.get("similar_to", []),
            similarity_score=rec.get("similarity_score", 0.0),
            preference_score=rec.get("preference_score", 0.0),
            combined_score=rec.get("combined_score", 0.0),
            is_fallback=rec.get("is_fallback", False),
        )
        db.add(entry)

    db.commit()
    # Refresh to get the generated timestamps and eager-loaded entries
    db.refresh(session_record)

    # ── Build response ───────────────────────────────────
    response = _session_to_response(session_record)

    logger.info(
        "Generated %d recommendations for user %s (fallback=%s, session=%s)",
        len(raw_recommendations),
        user.id,
        used_fallback,
        session_record.id,
    )

    return response


# ═════════════════════════════════════════════════════════
# GET /api/recommendations
# ═════════════════════════════════════════════════════════


@router.get("", response_model=RecommendationResponse)
def get_latest_recs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's most recently generated recommendations.

    Phase 3.5 change: reads from the database instead of an in-memory
    dict.  Recommendations now survive server restarts.

    Returns 404 if no recommendations have been generated yet.
    """
    # Get the most recent session for this user
    session_record = db.execute(
        select(RecommendationSession)
        .where(RecommendationSession.user_id == user.id)
        .order_by(RecommendationSession.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not session_record:
        raise HTTPException(
            status_code=404,
            detail=(
                "No recommendations generated yet. "
                "Click 'Generate' to get personalised recommendations."
            ),
        )

    return _session_to_response(session_record)


# ═════════════════════════════════════════════════════════
# GET /api/recommendations/history
# ═════════════════════════════════════════════════════════


@router.get("/history", response_model=RecommendationHistoryResponse)
def get_recommendation_history(
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List past recommendation sessions for the current user.

    Returns lightweight summaries (no full recommendation entries)
    so the frontend can render a history sidebar efficiently.

    Why lightweight?
    ────────────────
    A user might have 20+ sessions.  Each session has 10+ entries.
    Loading all entries for all sessions would be 200+ rows — slow
    and wasteful when we just need timestamps and counts for the
    sidebar.  Full entries are loaded on demand via GET /{session_id}.
    """
    sessions = db.execute(
        select(RecommendationSession)
        .where(RecommendationSession.user_id == user.id)
        .order_by(RecommendationSession.generated_at.desc())
        .limit(limit)
    ).scalars().all()

    summaries = [
        RecommendationSessionSummary(
            id=s.id,
            generated_at=s.generated_at,
            custom_query=s.custom_query,
            total_count=s.total_count,
            used_fallback=s.used_fallback,
        )
        for s in sessions
    ]

    return RecommendationHistoryResponse(
        sessions=summaries,
        total=len(summaries),
    )


# ═════════════════════════════════════════════════════════
# POST /api/recommendations/feedback
# ═════════════════════════════════════════════════════════


@router.post("/feedback", response_model=RecommendationFeedbackResponse)
def submit_feedback(
    body: RecommendationFeedbackRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record user feedback on a recommendation.

    Phase 3.5 changes:
    ───────────────────
    1. Persists feedback to the database (survives restarts).
    2. Uses upsert logic: if the user already gave feedback on this
       anime, we update it (latest feedback wins).
    3. Applies preference adjustments to the user's profile.

    Feedback effects:
    - "liked" → boost affinity for that anime's genres/themes
    - "disliked" → reduce affinity + exclude from future candidates
    - "watched" → add to exclusion set for future recommendations
    """
    # ── Look up anime metadata for the feedback record ───
    # We need genres/themes to compute preference adjustments later.
    # Try to find the anime in the most recent recommendation entries.
    rec_entry = db.execute(
        select(RecommendationEntry)
        .where(RecommendationEntry.mal_id == body.mal_id)
        .order_by(RecommendationEntry.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    anime_title = rec_entry.title if rec_entry else ""
    anime_genres = rec_entry.genres if rec_entry else None
    anime_themes = rec_entry.themes if rec_entry else None

    # ── Upsert feedback ──────────────────────────────────
    # Check if feedback already exists for this user + anime
    existing = db.execute(
        select(RecommendationFeedback).where(
            RecommendationFeedback.user_id == user.id,
            RecommendationFeedback.mal_id == body.mal_id,
        )
    ).scalar_one_or_none()

    if existing:
        # Update existing feedback (user changed their mind)
        existing.feedback_type = body.feedback
        existing.title = anime_title
        existing.genres = anime_genres
        existing.themes = anime_themes
    else:
        # Create new feedback
        feedback_record = RecommendationFeedback(
            user_id=user.id,
            mal_id=body.mal_id,
            title=anime_title,
            feedback_type=body.feedback,
            genres=anime_genres,
            themes=anime_themes,
        )
        db.add(feedback_record)

    db.commit()

    logger.info(
        "Feedback recorded: user=%s, mal_id=%d, feedback=%s (persisted)",
        user.id,
        body.mal_id,
        body.feedback,
    )

    return RecommendationFeedbackResponse(
        mal_id=body.mal_id,
        feedback=body.feedback,
        message="Feedback recorded and preferences updated!",
        profile_updated=True,
    )


# ═════════════════════════════════════════════════════════
# GET /api/recommendations/feedback
# ═════════════════════════════════════════════════════════


@router.get("/feedback", response_model=UserFeedbackMapResponse)
def get_user_feedback(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's feedback map for all recommended anime.

    Returns a {mal_id: feedback_type} mapping so the frontend can
    show which recommendations the user already rated.  This replaces
    the in-memory ``feedbackGiven`` state that was lost on page reload.

    Why a flat map?
    ───────────────
    The frontend just needs to know "has the user rated mal_id X?"
    A flat dict is the simplest structure for that lookup.  We don't
    need to know WHEN they rated it or which session it was in.
    """
    feedbacks = db.execute(
        select(RecommendationFeedback).where(
            RecommendationFeedback.user_id == user.id
        )
    ).scalars().all()

    feedback_map = {f.mal_id: f.feedback_type for f in feedbacks}

    return UserFeedbackMapResponse(feedback=feedback_map)


# ═════════════════════════════════════════════════════════
# GET /api/recommendations/{session_id}
# ═════════════════════════════════════════════════════════
#
# IMPORTANT: This route MUST be defined AFTER all other GET routes
# (/history, /feedback) because FastAPI matches routes in order.
# If /{session_id} came first, a request to /feedback would be
# caught by it with session_id="feedback".  This is a common
# FastAPI gotcha with path parameters.


@router.get("/{session_id}", response_model=RecommendationResponse)
def get_session_recs(
    session_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Load a specific past recommendation session.

    Used when the user clicks a session in the history sidebar.
    Returns the full recommendation entries for that session.

    Security: we verify the session belongs to the current user
    so users can't peek at each other's recommendations.
    """
    session_record = db.execute(
        select(RecommendationSession).where(
            RecommendationSession.id == session_id,
            RecommendationSession.user_id == user.id,  # security check
        )
    ).scalar_one_or_none()

    if not session_record:
        raise HTTPException(
            status_code=404,
            detail="Recommendation session not found.",
        )

    return _session_to_response(session_record)


# ═════════════════════════════════════════════════════════
# Private helpers
# ═════════════════════════════════════════════════════════


def _session_to_response(session_record: RecommendationSession) -> RecommendationResponse:
    """Convert a database session + entries to a RecommendationResponse.

    This is the mapping layer between the ORM model and the Pydantic
    schema.  It exists because the database model and API response
    have slightly different shapes (e.g., the response wraps entries
    in a ``recommendations`` list with metadata).

    Why not use ``model_validate`` directly?
    The ORM model has relationships and SQLAlchemy-specific types
    that don't map 1:1 to Pydantic.  This explicit mapping is
    clearer and less fragile than trying to auto-convert.
    """
    recommendation_items = [
        RecommendationItem(
            mal_id=entry.mal_id,
            title=entry.title,
            image_url=entry.image_url,
            genres=entry.genres or "",
            themes=entry.themes or "",
            synopsis=entry.synopsis or "",
            mal_score=entry.mal_score,
            year=entry.year,
            anime_type=entry.anime_type,
            reasoning=entry.reasoning,
            confidence=entry.confidence,
            similar_to=entry.similar_to or [],
            similarity_score=entry.similarity_score,
            preference_score=entry.preference_score,
            combined_score=entry.combined_score,
            is_fallback=entry.is_fallback,
        )
        for entry in session_record.entries
    ]

    return RecommendationResponse(
        recommendations=recommendation_items,
        generated_at=session_record.generated_at,
        total=len(recommendation_items),
        used_fallback=session_record.used_fallback,
        custom_query=session_record.custom_query,
    )


def _get_watched_mal_ids(user_id: str, db: Session) -> set[int]:
    """Get the set of MAL anime IDs the user has watched.

    Used to exclude already-watched anime from recommendations.
    We include all statuses except 'plan_to_watch' — if they've
    started it, dropped it, or completed it, don't recommend it.
    """
    anime_list = db.execute(
        select(AnimeList).where(AnimeList.user_id == user_id)
    ).scalar_one_or_none()

    if not anime_list:
        return set()

    entries = db.execute(
        select(AnimeEntry.mal_anime_id).where(
            AnimeEntry.anime_list_id == anime_list.id,
            AnimeEntry.watch_status != "plan_to_watch",
        )
    ).scalars().all()

    return set(entries)


def _get_feedback_exclude_ids(user_id: str, db: Session) -> set[int]:
    """Get MAL IDs that should be excluded based on user feedback.

    Excludes:
    - "disliked" anime — user explicitly said "not for me"
    - "watched" anime — user said they already watched it
      (this catches anime not on their MAL list)

    We do NOT exclude "liked" anime — the user liked it, but that
    doesn't mean they've watched it.  "liked" means "I'm interested",
    not "I've seen it".
    """
    feedback_ids = db.execute(
        select(RecommendationFeedback.mal_id).where(
            RecommendationFeedback.user_id == user_id,
            RecommendationFeedback.feedback_type.in_(["disliked", "watched"]),
        )
    ).scalars().all()

    return set(feedback_ids)
