"""Recommendation API endpoints.

This module is the "glue" between the frontend and the recommendation
engine.  It handles:

1. **Authentication** — only logged-in users can get recommendations
2. **Prerequisite checks** — user must have a preference profile first
3. **Orchestration** — coordinates the recommender service
4. **Caching** — stores generated recommendations so we don't re-call
   the LLM on every page refresh
5. **Response shaping** — converts raw dicts to typed Pydantic schemas

Endpoint design
───────────────
• POST /generate — expensive (calls LLM, ~3-5 seconds, costs money).
  Only called when user explicitly clicks "Generate Recommendations".

• GET / — cheap (reads from in-memory cache or returns empty).
  Called on page load to show previously generated recommendations.

• POST /feedback — records user feedback on a recommendation.
  Simple storage for now; Phase 3.5 can use this to refine the profile.

Why in-memory cache instead of database?
────────────────────────────────────────
Recommendations are ephemeral — they're regenerated on demand and
don't need to survive server restarts.  An in-memory dict keyed by
user_id is the simplest approach.  In production (Phase 4), we'd
move to Redis for multi-process support.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.logging import logger
from app.models.anime import AnimeEntry, AnimeList, UserPreferenceProfile
from app.models.user import User
from app.schemas.recommendation import (
    RecommendationFeedbackRequest,
    RecommendationFeedbackResponse,
    RecommendationItem,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services.recommender import generate_recommendations

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


# ── In-memory cache ──────────────────────────────────────
# Maps user_id → last generated RecommendationResponse.
# Simple dict for dev; Redis in production (Phase 4).
_recommendation_cache: dict[str, RecommendationResponse] = {}

# Maps user_id → list of feedback dicts.
# Simple storage for now; database table in Phase 4.
_feedback_store: dict[str, list[dict]] = {}


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

    Prerequisites:
    - User must be logged in
    - User must have imported their MAL list (preference profile exists)

    The generated recommendations are cached in memory so subsequent
    GET /api/recommendations calls return them instantly.
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

    # ── Get watched anime IDs (to exclude from recommendations) ──
    watched_mal_ids = _get_watched_mal_ids(user.id, db)

    # ── Generate recommendations ─────────────────────────
    try:
        raw_recommendations = generate_recommendations(
            preference_profile=profile.profile_data,
            watched_mal_ids=watched_mal_ids,
            num_recommendations=body.num_recommendations,
            custom_query=body.custom_query,
        )
    except ValueError as e:
        # No candidates found (empty vector store)
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        # OpenAI API key not configured
        raise HTTPException(status_code=500, detail=str(e))

    # ── Build response ───────────────────────────────────
    recommendation_items = [
        RecommendationItem(**rec) for rec in raw_recommendations
    ]

    used_fallback = any(rec.get("is_fallback", False) for rec in raw_recommendations)

    response = RecommendationResponse(
        recommendations=recommendation_items,
        generated_at=datetime.now(timezone.utc),
        total=len(recommendation_items),
        used_fallback=used_fallback,
        custom_query=body.custom_query,
    )

    # ── Cache the response ───────────────────────────────
    _recommendation_cache[user.id] = response

    logger.info(
        "Generated %d recommendations for user %s (fallback=%s)",
        len(recommendation_items),
        user.id,
        used_fallback,
    )

    return response


# ═════════════════════════════════════════════════════════
# GET /api/recommendations
# ═════════════════════════════════════════════════════════


@router.get("", response_model=RecommendationResponse)
def get_cached_recs(
    user: User = Depends(get_current_user),
):
    """Return the user's most recently generated recommendations.

    This is the cheap endpoint — no LLM call, just returns cached
    data.  Called on page load.

    Returns 404 if no recommendations have been generated yet.
    """
    cached = _recommendation_cache.get(user.id)

    if not cached:
        raise HTTPException(
            status_code=404,
            detail=(
                "No recommendations generated yet. "
                "Click 'Generate' to get personalised recommendations."
            ),
        )

    return cached


# ═════════════════════════════════════════════════════════
# POST /api/recommendations/feedback
# ═════════════════════════════════════════════════════════


@router.post("/feedback", response_model=RecommendationFeedbackResponse)
def submit_feedback(
    body: RecommendationFeedbackRequest,
    user: User = Depends(get_current_user),
):
    """Record user feedback on a recommendation.

    Stores the feedback for future use:
    - "liked" → boost similar anime in future recommendations
    - "disliked" → reduce similar anime
    - "watched" → add to exclusion list

    For now this is stored in memory.  Phase 4 will persist to DB
    and use it to refine the preference profile.
    """
    feedback_entry = {
        "mal_id": body.mal_id,
        "feedback": body.feedback,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if user.id not in _feedback_store:
        _feedback_store[user.id] = []

    _feedback_store[user.id].append(feedback_entry)

    logger.info(
        "Feedback recorded: user=%s, mal_id=%d, feedback=%s",
        user.id,
        body.mal_id,
        body.feedback,
    )

    return RecommendationFeedbackResponse(
        mal_id=body.mal_id,
        feedback=body.feedback,
    )


# ═════════════════════════════════════════════════════════
# Private helpers
# ═════════════════════════════════════════════════════════


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
