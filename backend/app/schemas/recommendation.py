"""Pydantic schemas for the recommendation API.

These schemas define the contract between frontend and backend for
the recommendation endpoints.  They serve three purposes:

1. **Request validation** — ensures incoming data is well-formed
   (e.g. num_recommendations is a positive integer, not "banana")

2. **Response serialisation** — controls exactly what JSON the
   frontend receives.  We can add/remove fields without changing
   the database or service layer.

3. **Auto-documentation** — FastAPI generates Swagger docs from
   these schemas, so the frontend team (or future you) can see
   exactly what each endpoint accepts and returns.

Design decisions
────────────────
• RecommendationItem includes both LLM-generated fields (reasoning,
  confidence, similar_to) and metadata fields (genres, year, score).
  The frontend needs both to render a rich recommendation card.

• The ``is_fallback`` flag tells the frontend whether the LLM was
  used or not.  If True, the frontend can show a subtle notice like
  "AI reasoning unavailable — showing best matches from your profile."

• RecommendationFeedbackRequest is simple for now (liked/disliked).
  In Phase 3.5 we can expand it with more nuanced feedback.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ═════════════════════════════════════════════════════════
# Request schemas
# ═════════════════════════════════════════════════════════


class RecommendationRequest(BaseModel):
    """POST /api/recommendations/generate — request body.

    All fields are optional.  With no fields, we generate 10
    recommendations using the user's full preference profile.
    """

    num_recommendations: int = Field(
        default=10,
        ge=1,
        le=25,
        description="How many recommendations to generate (1-25).",
    )
    custom_query: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Optional custom search query for the retriever. "
            "Used for functional buttons like 'more action anime' "
            "or 'something shorter'. Overrides auto-generated queries."
        ),
        examples=["dark psychological thriller", "short anime under 13 episodes"],
    )
    min_score: float | None = Field(
        default=7.0,
        ge=0.0,
        le=10.0,
        description="Minimum MAL community score filter. Set to null to disable.",
    )


class RecommendationFeedbackRequest(BaseModel):
    """POST /api/recommendations/feedback — user rates a recommendation.

    Simple for now: liked, disliked, or already watched.
    In Phase 3.5 we can add more nuanced feedback (e.g. "not my
    genre", "too long", "already seen similar").
    """

    mal_id: int = Field(
        ...,
        description="MAL ID of the recommended anime.",
    )
    feedback: str = Field(
        ...,
        pattern="^(liked|disliked|watched)$",
        description="User's feedback: 'liked', 'disliked', or 'watched'.",
        examples=["liked"],
    )


# ═════════════════════════════════════════════════════════
# Response schemas
# ═════════════════════════════════════════════════════════


class RecommendationItem(BaseModel):
    """A single anime recommendation with AI reasoning.

    This is the core data structure the frontend renders as a
    recommendation card.  It includes:
    - Anime metadata (for display)
    - LLM-generated reasoning (the "why")
    - Retriever scores (for transparency/debugging)
    """

    # ── Anime identity ───────────────────────────────────
    mal_id: int
    title: str
    image_url: str | None = None

    # ── Anime metadata ───────────────────────────────────
    genres: str = ""
    themes: str = ""
    synopsis: str = ""
    mal_score: float | None = None
    year: int | None = None
    anime_type: str | None = None

    # ── AI-generated fields ──────────────────────────────
    reasoning: str = Field(
        description=(
            "2-3 sentence explanation of WHY this user would enjoy "
            "this anime, referencing their specific preferences."
        ),
    )
    confidence: str = Field(
        description="How confident the AI is: 'high', 'medium', or 'low'.",
        pattern="^(high|medium|low)$",
    )
    similar_to: list[str] = Field(
        default_factory=list,
        description="Titles from the user's watched list that are similar.",
    )

    # ── Retriever scores (for transparency) ──────────────
    similarity_score: float = 0.0
    preference_score: float = 0.0
    combined_score: float = 0.0

    # ── Fallback flag ────────────────────────────────────
    is_fallback: bool = Field(
        default=False,
        description=(
            "True if this recommendation was generated without the LLM "
            "(deterministic fallback). Frontend can show a notice."
        ),
    )


class RecommendationResponse(BaseModel):
    """GET/POST /api/recommendations — the full response.

    Wraps the list of recommendations with metadata about
    when they were generated and whether fallback was used.
    """

    recommendations: list[RecommendationItem]
    generated_at: datetime
    total: int = Field(description="Number of recommendations returned.")
    used_fallback: bool = Field(
        default=False,
        description="True if any recommendations used the deterministic fallback.",
    )
    custom_query: str | None = Field(
        default=None,
        description="The custom query used, if any.",
    )


class RecommendationFeedbackResponse(BaseModel):
    """Response after submitting feedback on a recommendation."""

    mal_id: int
    feedback: str
    message: str = "Feedback recorded. Thank you!"
