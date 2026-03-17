"""Demo API endpoints — Phase 4.5.

Public, unauthenticated endpoints that serve pre-seeded demo data.
These power the landing page demo section so visitors can see Machi
in action without creating an account.

All endpoints are read-only.  They look up the demo user's data
from the database (seeded by ``make seed-demo``) and return it in
the same format as the authenticated endpoints.

Why separate endpoints instead of auto-login?
─────────────────────────────────────────────
• Simpler — no cookie/session complexity for anonymous visitors
• More secure — no auth tokens floating around for a demo account
• Cacheable — responses are the same for every visitor
• The landing page just fetches public JSON, renders it, done
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.exceptions import AppError
from app.models.anime import UserPreferenceProfile
from app.models.recommendation import RecommendationSession
from app.models.user import User
from app.schemas.recommendation import (
    RecommendationItem,
    RecommendationResponse,
)

router = APIRouter(prefix="/demo", tags=["Demo"])

DEMO_EMAIL = "demo@machi.app"


def _get_demo_user(db: Session) -> User:
    """Look up the demo user, or raise 404 if not seeded."""
    user = db.execute(
        select(User).where(User.email == DEMO_EMAIL)
    ).scalar_one_or_none()

    if not user:
        raise AppError(
            code="NOT_FOUND",
            message=(
                "Demo data not available. "
                "Run 'make seed-demo' to populate demo data."
            ),
            status_code=404,
        )
    return user


@router.get("/profile")
def get_demo_profile(db: Session = Depends(get_db)):
    """Return the demo user's preference profile.

    Public endpoint — no authentication required.
    Returns the same profile_data structure as GET /api/mal/profile
    but for the pre-seeded demo user.
    """
    user = _get_demo_user(db)

    profile = db.execute(
        select(UserPreferenceProfile).where(
            UserPreferenceProfile.user_id == user.id
        )
    ).scalar_one_or_none()

    if not profile:
        raise AppError(
            code="NOT_FOUND",
            message="Demo profile not found. Run 'make seed-demo'.",
            status_code=404,
        )

    return profile.profile_data


@router.get("/recommendations", response_model=RecommendationResponse)
def get_demo_recommendations(db: Session = Depends(get_db)):
    """Return the demo user's pre-generated recommendations.

    Public endpoint — no authentication required.
    Returns the same structure as GET /api/recommendations
    but for the pre-seeded demo user.
    """
    user = _get_demo_user(db)

    session_record = db.execute(
        select(RecommendationSession)
        .where(RecommendationSession.user_id == user.id)
        .order_by(RecommendationSession.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not session_record:
        raise AppError(
            code="NOT_FOUND",
            message="Demo recommendations not found. Run 'make seed-demo'.",
            status_code=404,
        )

    items = [
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
        recommendations=items,
        generated_at=session_record.generated_at,
        total=len(items),
        used_fallback=session_record.used_fallback,
        custom_query=session_record.custom_query,
    )
