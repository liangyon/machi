"""Pydantic schemas for the Taste Card feature."""

from pydantic import BaseModel, Field


class DarkHorsePick(BaseModel):
    """A contrarian pick: user rated it highly, but community scores it low."""

    mal_anime_id: int
    title: str
    image_url: str | None = None
    user_score: int
    mal_score: float | None = None
    genres: str | None = None


class TasteCardResponse(BaseModel):
    """Full taste card payload returned by GET /api/taste-card."""

    # Categorical archetype
    archetype: str = Field(description="Genre label + intensity modifier, e.g. 'Fantasy Veteran'")
    roast: str = Field(description="Pre-written one-liner matched to the archetype")
    vibe: str | None = Field(default=None, description="Optional sub-label from theme affinity, e.g. 'Isekai Escapist'")
    reasoning: str = Field(description="2-3 sentence explanation of why the user received this archetype")

    # Computed signals
    top_genres: list[str] = Field(description="Top 3-5 genres by affinity score")
    favorite_era: str = Field(description="Peak decade of watch history, e.g. '2010s'")
    dark_horse: DarkHorsePick | None = Field(
        description="Highest user-rated show where community score < 7.5"
    )
    taste_traits: list[str] = Field(description="3-4 rule-based personality chips")

    # Summary stats
    entry_count: int
    avg_score: float

    # Source badge
    source: str | None = None  # "mal" | "anilist"
    imported_username: str | None = None

    generated_at: str
