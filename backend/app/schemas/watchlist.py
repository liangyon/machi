"""Pydantic schemas for the watchlist API."""

from datetime import datetime
from pydantic import BaseModel, Field


class WatchlistItemResponse(BaseModel):
    """A single item on the user's watchlist."""

    id: str
    mal_id: int
    title: str
    image_url: str | None = None
    genres: str | None = None
    themes: str | None = None
    mal_score: float | None = None
    year: int | None = None
    anime_type: str | None = None
    status: str = "to_watch"
    user_rating: int | None = None
    reaction: str | None = None
    source: str = "recommendation"
    notes: str | None = None
    added_at: datetime


class WatchlistResponse(BaseModel):
    """Response for GET /watchlist."""

    items: list[WatchlistItemResponse]
    total: int


class WatchlistAddRequest(BaseModel):
    """Request to add an anime to the watchlist."""

    mal_id: int
    title: str
    image_url: str | None = None
    genres: str | None = None
    themes: str | None = None
    mal_score: float | None = None
    year: int | None = None
    anime_type: str | None = None
    source: str = Field(default="recommendation", pattern="^(recommendation|manual)$")
    notes: str | None = None


class WatchlistAddResponse(BaseModel):
    """Response for POST /watchlist."""

    item: WatchlistItemResponse
    message: str
    already_existed: bool = False


class WatchlistUpdateRequest(BaseModel):
    """Request to update a watchlist entry (status, rating, reaction)."""

    status: str | None = Field(
        default=None, pattern="^(to_watch|watching|completed|dropped)$"
    )
    user_rating: int | None = Field(default=None, ge=1, le=10)
    reaction: str | None = None
    notes: str | None = None


class WatchlistUpdateResponse(BaseModel):
    """Response for PATCH /watchlist/{mal_id}."""

    item: WatchlistItemResponse
    message: str


class WatchlistRemoveResponse(BaseModel):
    """Response for DELETE /watchlist/{mal_id}."""

    mal_id: int
    message: str
