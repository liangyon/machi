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

• Phase 3.5 additions:
  - ``RecommendationSessionSummary`` — lightweight view of a past
    session for the history endpoint (id, timestamp, query, count).
  - ``RecommendationHistoryResponse`` — wraps a list of summaries.
  - ``RecommendationFeedbackResponse`` now includes ``profile_updated``
    to tell the frontend whether the feedback was applied to the
    user's preference profile.
  - ``UserFeedbackMapResponse`` — returns a {mal_id: feedback_type}
    map so the frontend can show which recs the user already rated.
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
    """Response after submitting feedback on a recommendation.

    Phase 3.5: Added ``profile_updated`` flag so the frontend knows
    whether the feedback was applied to the user's preference profile.
    This lets the UI show "Your preferences have been updated" or
    prompt the user to regenerate recommendations.
    """

    mal_id: int
    feedback: str
    message: str = "Feedback recorded. Thank you!"
    profile_updated: bool = Field(
        default=False,
        description=(
            "True if the user's preference profile was adjusted "
            "based on this feedback."
        ),
    )


# ═════════════════════════════════════════════════════════
# Phase 3.5 — History & feedback persistence schemas
# ═════════════════════════════════════════════════════════


class RecommendationSessionSummary(BaseModel):
    """Lightweight summary of a past recommendation session.

    Used by the GET /history endpoint.  Contains just enough info
    to render a history sidebar entry:
    - When it was generated
    - What query was used (if any)
    - How many recommendations it produced
    - Whether fallback was used

    We deliberately exclude the full recommendation entries here —
    those are loaded on demand when the user clicks a session.
    This keeps the history endpoint fast (no loading 10+ recs
    per session × 20 sessions = 200+ rows).
    """

    id: str
    generated_at: datetime
    custom_query: str | None = None
    total_count: int = 0
    used_fallback: bool = False


class RecommendationHistoryResponse(BaseModel):
    """GET /api/recommendations/history — list of past sessions.

    Returns the most recent sessions (up to ``limit``) so the
    frontend can render a history sidebar or dropdown.
    """

    sessions: list[RecommendationSessionSummary]
    total: int = Field(description="Number of sessions returned.")


class UserFeedbackMapResponse(BaseModel):
    """GET /api/recommendations/feedback — user's feedback map.

    Returns a {mal_id: feedback_type} mapping so the frontend can
    show which recommendations the user already rated, even after
    a page reload.  This replaces the in-memory ``feedbackGiven``
    state in the frontend.

    Example::

        {
            "feedback": {
                "52991": "liked",
                "38524": "disliked",
                "11061": "watched"
            }
        }
    """

    feedback: dict[int, str] = Field(
        default_factory=dict,
        description="Mapping of MAL ID → feedback type (liked/disliked/watched).",
    )
