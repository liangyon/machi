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

from datetime import datetime, timedelta, timezone
from time import perf_counter
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import logger
from app.core.metrics import (
    RecommendationJobSnapshot,
    get_metrics_summary,
    get_recent_jobs,
    increment,
    observe_latency,
    record_recent_job,
)
from app.db.session import SessionLocal
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
    RecommendationGenerateAccepted,
    RecommendationHistoryResponse,
    RecommendationItem,
    RecommendationJobStatusResponse,
    RecommendationRequest,
    RecommendationResponse,
    RecommendationSessionSummary,
    UserFeedbackMapResponse,
)
from app.services.preference_analyzer import apply_feedback_adjustments
from app.services.recommender import GuardrailError, generate_recommendations

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


# Lightweight in-process job status store.
# For current single-instance scope, this is enough to power progress UI.
_generation_jobs: dict[str, dict] = {}
_generation_jobs_lock = Lock()


# ═════════════════════════════════════════════════════════
# POST /api/recommendations/generate
# ═════════════════════════════════════════════════════════


@router.post("/generate", response_model=RecommendationGenerateAccepted, status_code=202)
def generate_recs(
    body: RecommendationRequest,
    background_tasks: BackgroundTasks,
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
    # ── Check prerequisites up-front for fast failure ───
    if body.num_recommendations > settings.RECOMMEND_MAX_ITEMS_PER_REQUEST:
        raise AppError(
            code="VALIDATION_ERROR",
            message=(
                "Requested recommendation count exceeds configured limit. "
                f"Maximum is {settings.RECOMMEND_MAX_ITEMS_PER_REQUEST}."
            ),
            status_code=422,
            details={
                "field": "num_recommendations",
                "max": settings.RECOMMEND_MAX_ITEMS_PER_REQUEST,
            },
        )

    if body.custom_query and len(body.custom_query) > settings.RECOMMEND_MAX_CUSTOM_QUERY_CHARS:
        raise AppError(
            code="VALIDATION_ERROR",
            message="Custom query exceeds maximum length.",
            status_code=422,
            details={
                "field": "custom_query",
                "max_chars": settings.RECOMMEND_MAX_CUSTOM_QUERY_CHARS,
            },
        )

    profile = db.execute(
        select(UserPreferenceProfile).where(
            UserPreferenceProfile.user_id == user.id
        )
    ).scalar_one_or_none()

    if not profile:
        raise AppError(
            code="NOT_FOUND",
            message=(
                "No preference profile found. "
                "Import your MAL list first via POST /api/mal/import."
            ),
            status_code=404,
        )

    # ── Queue background generation job ──────────────────
    job_id = str(uuid4())
    _set_job(
        job_id,
        {
            "job_id": job_id,
            "user_id": user.id,
            "status": "queued",
            "progress": 0,
            "stage": "queued",
            "error": None,
            "session_id": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    normalized_query = _sanitize_custom_query(body.custom_query)

    background_tasks.add_task(
        _run_generation_job,
        job_id,
        user.id,
        body.num_recommendations,
        normalized_query,
    )

    logger.info(
        "recommendation_job_enqueued job_id=%s user_id=%s num_recommendations=%d",
        job_id,
        user.id,
        body.num_recommendations,
    )

    return RecommendationGenerateAccepted(
        job_id=job_id,
        status="queued",
        progress=0,
        stage="queued",
    )


@router.get("/status/{job_id}", response_model=RecommendationJobStatusResponse)
def get_generation_status(
    job_id: str,
    user: User = Depends(get_current_user),
):
    """Return current status for a recommendation generation job."""
    job = _get_job(job_id)

    if not job or job.get("user_id") != user.id:
        raise AppError(
            code="NOT_FOUND",
            message="Generation job not found.",
            status_code=404,
        )

    return RecommendationJobStatusResponse(
        job_id=job_id,
        status=job.get("status", "queued"),
        progress=int(job.get("progress", 0)),
        stage=job.get("stage", "queued"),
        error=job.get("error"),
        session_id=job.get("session_id"),
    )


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
        raise AppError(
            code="NOT_FOUND",
            message=(
                "No recommendations generated yet. "
                "Click 'Generate' to get personalised recommendations."
            ),
            status_code=404,
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


@router.get("/jobs/recent")
def get_recent_generation_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    """Return recent recommendation generation job summaries.

    Current scope is single-instance visibility for quick diagnostics.
    """
    jobs = [j for j in get_recent_jobs(limit=limit * 2) if j.get("user_id") == user.id]
    return {
        "jobs": jobs[:limit],
        "total": len(jobs[:limit]),
        "metrics": get_metrics_summary(),
    }


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
        raise AppError(
            code="NOT_FOUND",
            message="Recommendation session not found.",
            status_code=404,
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


def _get_recently_recommended_ids(user_id: str, db: Session, days: int = 30) -> set[int]:
    """Get MAL IDs that were recommended in the last `days` days.

    Excludes these from new generations so users always get fresh picks
    rather than the same anime repeatedly appearing across sessions.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    ids = db.execute(
        select(distinct(RecommendationEntry.mal_id))
        .join(RecommendationSession, RecommendationEntry.session_id == RecommendationSession.id)
        .where(
            RecommendationSession.user_id == user_id,
            RecommendationSession.generated_at >= cutoff,
        )
    ).scalars().all()
    return set(ids)


def _set_job(job_id: str, payload: dict) -> None:
    with _generation_jobs_lock:
        _generation_jobs[job_id] = payload


def _get_job(job_id: str) -> dict | None:
    with _generation_jobs_lock:
        job = _generation_jobs.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **updates) -> None:
    with _generation_jobs_lock:
        current = _generation_jobs.get(job_id)
        if not current:
            return
        current.update(updates)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        _generation_jobs[job_id] = current


def _sanitize_custom_query(custom_query: str | None) -> str | None:
    if not custom_query:
        return None
    query = custom_query.strip()
    return query if query else None


def _run_generation_job(
    job_id: str,
    user_id: str,
    num_recommendations: int,
    custom_query: str | None,
) -> None:
    """Background task that generates and persists recommendation session."""
    db = SessionLocal()
    started = perf_counter()
    increment("recommendation_total")
    try:
        _update_job(job_id, status="running", progress=10, stage="validating")

        profile = db.execute(
            select(UserPreferenceProfile).where(UserPreferenceProfile.user_id == user_id)
        ).scalar_one_or_none()
        if not profile:
            raise ValueError("No preference profile found. Import your MAL list first.")

        _update_job(job_id, progress=25, stage="loading_profile")
        feedbacks = db.execute(
            select(RecommendationFeedback).where(RecommendationFeedback.user_id == user_id)
        ).scalars().all()
        adjusted_profile = apply_feedback_adjustments(profile.profile_data, feedbacks)

        _update_job(job_id, progress=45, stage="retrieving_candidates")
        watched_mal_ids = _get_watched_mal_ids(user_id, db)
        feedback_exclude_ids = _get_feedback_exclude_ids(user_id, db)
        recently_recommended_ids = _get_recently_recommended_ids(user_id, db, days=30)
        all_exclude_ids = watched_mal_ids | feedback_exclude_ids | recently_recommended_ids

        _update_job(job_id, progress=75, stage="generating_recommendations")
        raw_recommendations = generate_recommendations(
            preference_profile=adjusted_profile,
            watched_mal_ids=all_exclude_ids,
            num_recommendations=num_recommendations,
            custom_query=custom_query,
            timeout_budget_seconds=settings.RECOMMEND_JOB_TIMEOUT_SECONDS,
            max_input_chars=settings.LLM_MAX_INPUT_CHARS,
            max_estimated_cost_usd=settings.LLM_MAX_ESTIMATED_COST_USD,
        )

        _update_job(job_id, progress=90, stage="persisting")
        used_fallback = any(rec.get("is_fallback", False) for rec in raw_recommendations)

        session_record = RecommendationSession(
            user_id=user_id,
            custom_query=custom_query,
            used_fallback=used_fallback,
            total_count=len(raw_recommendations),
        )
        db.add(session_record)
        db.flush()

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

        _update_job(
            job_id,
            status="succeeded",
            progress=100,
            stage="completed",
            session_id=session_record.id,
            error=None,
        )

        elapsed_ms = int((perf_counter() - started) * 1000)
        observe_latency(elapsed_ms)
        increment("recommendation_success")
        if used_fallback:
            increment("recommendation_fallback")

        record_recent_job(
            RecommendationJobSnapshot(
                job_id=job_id,
                user_id=user_id,
                status="succeeded",
                stage="completed",
                duration_ms=elapsed_ms,
                used_fallback=used_fallback,
                error_code=None,
                error=None,
            )
        )

        logger.info(
            "recommendation_job_succeeded job_id=%s user_id=%s total=%d fallback=%s session_id=%s duration_ms=%d",
            job_id,
            user_id,
            len(raw_recommendations),
            used_fallback,
            session_record.id,
            elapsed_ms,
        )
    except GuardrailError as e:
        db.rollback()
        increment("recommendation_failed")
        _update_job(job_id, status="failed", stage="failed", error=e.message, error_code=e.code)
        record_recent_job(
            RecommendationJobSnapshot(
                job_id=job_id,
                user_id=user_id,
                status="failed",
                stage="failed",
                duration_ms=int((perf_counter() - started) * 1000),
                used_fallback=False,
                error_code=e.code,
                error=e.message,
            )
        )
        logger.warning(
            "recommendation_job_failed job_id=%s user_id=%s code=%s message=%s",
            job_id,
            user_id,
            e.code,
            e.message,
        )
    except (ValueError, RuntimeError) as e:
        db.rollback()
        increment("recommendation_failed")
        _update_job(job_id, status="failed", stage="failed", error=str(e), error_code="UPSTREAM_UNAVAILABLE")
        record_recent_job(
            RecommendationJobSnapshot(
                job_id=job_id,
                user_id=user_id,
                status="failed",
                stage="failed",
                duration_ms=int((perf_counter() - started) * 1000),
                used_fallback=False,
                error_code="UPSTREAM_UNAVAILABLE",
                error=str(e),
            )
        )
        logger.warning("recommendation_job_failed job_id=%s user_id=%s error=%s", job_id, user_id, e)
    except Exception as e:  # pragma: no cover - defensive catch
        db.rollback()
        increment("recommendation_failed")
        _update_job(
            job_id,
            status="failed",
            stage="failed",
            error="Internal generation error",
            error_code="INTERNAL_ERROR",
        )
        record_recent_job(
            RecommendationJobSnapshot(
                job_id=job_id,
                user_id=user_id,
                status="failed",
                stage="failed",
                duration_ms=int((perf_counter() - started) * 1000),
                used_fallback=False,
                error_code="INTERNAL_ERROR",
                error="Internal generation error",
            )
        )
        logger.exception("recommendation_job_failed_unexpected job_id=%s user_id=%s error=%s", job_id, user_id, e)
    finally:
        db.close()
