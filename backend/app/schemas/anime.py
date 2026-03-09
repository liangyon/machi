"""Pydantic schemas for anime-related API endpoints.

These schemas define the *API contract* — what the frontend sends us
and what we send back.  They're deliberately different from the ORM
models:

• Request schemas validate incoming data (e.g. MAL username).
• Response schemas control what we expose (we might hide internal IDs
  or reshape nested data for the frontend's convenience).
• The preference profile response flattens the JSON blob into typed
  fields so the frontend gets a predictable shape.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ── MAL Import ───────────────────────────────────────────


class MALImportRequest(BaseModel):
    """POST /api/mal/import — kick off a MAL list import."""

    mal_username: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="The MyAnimeList username to import.",
        examples=["Zephyrot"],
    )


class MALImportResponse(BaseModel):
    """Response after starting a MAL import."""

    anime_list_id: str
    mal_username: str
    sync_status: str
    message: str


# ── MAL Sync Status ──────────────────────────────────────


class MALSyncStatus(BaseModel):
    """GET /api/mal/status — check import progress."""

    anime_list_id: str
    mal_username: str
    sync_status: str  # pending | in_progress | completed | failed
    total_entries: int
    last_synced_at: datetime | None


# ── Anime Entry (for list display) ──────────────────────


class AnimeEntryResponse(BaseModel):
    """A single anime from the user's imported list."""

    mal_anime_id: int
    title: str
    title_english: str | None = None
    image_url: str | None = None
    watch_status: str
    user_score: int
    episodes_watched: int
    total_episodes: int | None = None
    anime_type: str | None = None
    genres: str | None = None
    themes: str | None = None
    year: int | None = None
    mal_score: float | None = None

    model_config = {"from_attributes": True}


class AnimeListResponse(BaseModel):
    """GET /api/mal/list — the user's full imported anime list."""

    mal_username: str
    sync_status: str
    total_entries: int
    last_synced_at: datetime | None
    entries: list[AnimeEntryResponse]


# ── Genre Affinity ───────────────────────────────────────


class GenreAffinity(BaseModel):
    """How much a user likes a particular genre."""

    genre: str
    count: int = Field(description="Number of anime watched in this genre")
    avg_score: float = Field(description="User's average score for this genre")
    affinity: float = Field(
        description="Normalised affinity score (0–1) combining count and rating"
    )


# ── Preference Profile ──────────────────────────────────


class PreferenceProfileResponse(BaseModel):
    """GET /api/mal/profile — the user's computed taste profile.

    This is a typed view over the JSON blob stored in
    UserPreferenceProfile.profile_data.  We type it here so the
    frontend gets a predictable contract even though the backend
    stores it flexibly.
    """

    total_watched: int
    total_scored: int
    mean_score: float
    score_distribution: dict[str, int]  # {"10": 5, "9": 12, ...}
    genre_affinity: list[GenreAffinity]
    theme_affinity: list[GenreAffinity]  # reuse same shape
    studio_affinity: list[GenreAffinity]
    preferred_formats: dict[str, int]  # {"TV": 100, "Movie": 30}
    completion_rate: float  # 0.0–1.0
    top_10: list[AnimeEntryResponse]
    watch_era_preference: dict[str, int]  # {"2020s": 40, "2010s": 60}
    generated_at: datetime
