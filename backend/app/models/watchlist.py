"""Watchlist model — user's to-watch list.

Stores anime that users have marked as "interested" from recommendations.
When a user clicks "Interested" (thumbs up) on a recommendation, the anime
is automatically added to their watchlist.

This is separate from the MAL watch list (which is imported from MyAnimeList).
The watchlist is Machi-native — it tracks anime the user wants to watch
based on our recommendations.

Design notes
────────────
• One entry per user per anime (unique constraint on user_id + mal_id).
• We denormalise anime metadata (title, image_url, genres) so we can
  render the watchlist without joining to the catalog table.
• The ``source`` field tracks where the anime was added from
  (e.g. "recommendation" or "manual") for analytics.
• ``added_at`` tracks when the user added it, useful for sorting
  ("recently added" view).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    Float,
    Text,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class WatchlistEntry(Base):
    """A single anime on a user's to-watch list.

    Created when a user marks a recommendation as "interested" (liked),
    or manually adds an anime to their watchlist.
    """

    __tablename__ = "watchlist_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "mal_id", name="uq_watchlist_user_anime"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # ── Owner ────────────────────────────────────────────
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )

    # ── Anime identity ───────────────────────────────────
    mal_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(512))
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # ── Anime metadata (denormalised snapshot) ───────────
    genres: Mapped[str | None] = mapped_column(Text, nullable=True)
    themes: Mapped[str | None] = mapped_column(Text, nullable=True)
    mal_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anime_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Status tracking ──────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20), default="to_watch"
    )  # to_watch | watching | completed | dropped

    # ── User reaction (recorded after watching) ──────────
    user_rating: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 1-10 score, set after watching
    reaction: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # free-text reaction/review

    # ── Source tracking ──────────────────────────────────
    source: Mapped[str] = mapped_column(
        String(50), default="recommendation"
    )  # recommendation | manual

    # ── Notes (optional user note about why they want to watch) ──
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamps ───────────────────────────────────────
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<WatchlistEntry user_id={self.user_id!r} "
            f"mal_id={self.mal_id} title={self.title!r}>"
        )
