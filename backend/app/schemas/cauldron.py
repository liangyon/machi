"""Pydantic schemas for the Cauldron API.

Cauldron is the seed-based vibe-matching mode: the user picks 1–3 "seed"
anime and gets recommendations matching that exact vibe — no MAL/AniList
import required.

These schemas define the request/response contract for:
  - Seed search (finding anime to use as seeds)
  - Cauldron generation (async job, same polling pattern as /recommendations)
  - Cauldron results (same RecommendationItem shape, cauldron-flavoured)
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.recommendation import (
    RecommendationGenerateAccepted,
    RecommendationItem,
    RecommendationJobStatusResponse,
)

# Re-export for convenience — callers can import from here instead of hunting
# the recommendation schema module.
__all__ = [
    "CauldronSearchResult",
    "CauldronSearchResponse",
    "CauldronGenerateRequest",
    "CauldronGenerateAccepted",
    "CauldronJobStatusResponse",
    "CauldronResultsResponse",
]

CauldronGenerateAccepted = RecommendationGenerateAccepted
CauldronJobStatusResponse = RecommendationJobStatusResponse


# ═════════════════════════════════════════════════════════
# Seed search
# ═════════════════════════════════════════════════════════


class CauldronSearchResult(BaseModel):
    """A single anime result from the seed search endpoint."""

    mal_id: int
    title: str
    title_english: str | None = None
    image_url: str | None = None
    year: int | None = None
    anime_type: str | None = None
    genres: str | None = None
    mal_score: float | None = None


class CauldronSearchResponse(BaseModel):
    """GET /api/cauldron/search — list of matching anime for seed picker."""

    results: list[CauldronSearchResult]
    total: int


# ═════════════════════════════════════════════════════════
# Generation request
# ═════════════════════════════════════════════════════════


class CauldronGenerateRequest(BaseModel):
    """POST /api/cauldron/generate — request body.

    Provide 1–3 seed MAL IDs. The engine will find anime that match the
    combined vibe/feel/themes of those seeds.
    """

    seed_mal_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=3,
        description="1–3 MAL IDs of seed anime to vibe-match against.",
    )
    num_recommendations: int = Field(
        default=5,
        ge=1,
        le=10,
        description="How many recommendations to generate (1–10).",
    )

    @model_validator(mode="after")
    def no_duplicate_seeds(self) -> "CauldronGenerateRequest":
        if len(self.seed_mal_ids) != len(set(self.seed_mal_ids)):
            raise ValueError("seed_mal_ids must not contain duplicates.")
        return self


# ═════════════════════════════════════════════════════════
# Results response
# ═════════════════════════════════════════════════════════


class CauldronResultsResponse(BaseModel):
    """GET /api/cauldron/results/{session_id} — completed cauldron session.

    Same recommendations shape as the standard endpoint, but also includes
    the seed titles so the frontend can display "Based on: Title1, Title2".
    """

    session_id: str
    seed_titles: list[str] = Field(
        description="Display names of the seed anime used to brew this session.",
    )
    recommendations: list[RecommendationItem]
    generated_at: datetime
    total: int
    used_fallback: bool = False
