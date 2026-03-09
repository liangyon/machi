"""Anime-related ORM models for MAL list ingestion and preference tracking.

Design notes
────────────
• AnimeList is the "header" linking a Machi user to a MAL username.
  One user → one AnimeList (for now).  We keep it separate from User so
  the auth layer stays clean and we can support other list sources later.

• AnimeEntry stores each anime on the user's list together with the
  anime's metadata (genres, synopsis …).  In Phase 2 we'll normalise
  anime metadata into its own table; for now co-locating it keeps
  queries simple and avoids premature abstraction.

• UserPreferenceProfile holds the *computed* taste summary as a JSON
  blob.  JSON is intentional — the profile schema will evolve as we
  refine the preference analyser, and we don't want a migration every
  time we add a new signal.  The LLM consumes it as a whole document
  anyway.
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
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class AnimeList(Base):
    """A user's imported MAL anime list (header / metadata)."""

    __tablename__ = "anime_lists"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # ── Owner ────────────────────────────────────────────
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,          # one list per user (for now)
        index=True,
    )

    # ── MAL identity ─────────────────────────────────────
    mal_username: Mapped[str] = mapped_column(String(255), index=True)

    # ── Sync metadata ────────────────────────────────────
    total_entries: Mapped[int] = mapped_column(Integer, default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | in_progress | completed | failed

    # ── Timestamps ───────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relationships ────────────────────────────────────
    entries: Mapped[list["AnimeEntry"]] = relationship(
        back_populates="anime_list",
        cascade="all, delete-orphan",
        lazy="selectin",       # eager-load entries when we fetch a list
    )

    def __repr__(self) -> str:
        return (
            f"<AnimeList id={self.id!r} user_id={self.user_id!r} "
            f"mal_username={self.mal_username!r} status={self.sync_status!r}>"
        )


class AnimeEntry(Base):
    """A single anime on a user's MAL list, with metadata snapshot.

    Stores both the *user's* relationship to the anime (score, status,
    episodes watched) and a snapshot of the anime's own metadata (genres,
    synopsis, etc.) so we can analyse preferences without extra API calls.
    """

    __tablename__ = "anime_entries"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # ── Parent list ──────────────────────────────────────
    anime_list_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("anime_lists.id", ondelete="CASCADE"),
        index=True,
    )

    # ── MAL anime identity ───────────────────────────────
    mal_anime_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(512))
    title_english: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # ── User's relationship to this anime ────────────────
    watch_status: Mapped[str] = mapped_column(
        String(20)
    )  # watching | completed | on_hold | dropped | plan_to_watch
    user_score: Mapped[int] = mapped_column(Integer, default=0)  # 0 = unscored
    episodes_watched: Mapped[int] = mapped_column(Integer, default=0)

    # ── Anime metadata (snapshot from Jikan) ─────────────
    total_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anime_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # TV | Movie | OVA | ONA | Special | Music
    anime_status: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )  # Finished Airing | Currently Airing | Not yet aired
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    genres: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # comma-separated: "Action, Adventure, Fantasy"
    themes: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # comma-separated: "Isekai, Military"
    studios: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # comma-separated studio names
    season: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "winter 2023"
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mal_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # community score
    mal_members: Mapped[int | None] = mapped_column(Integer, nullable=True)  # popularity

    # ── Timestamps ───────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────
    anime_list: Mapped["AnimeList"] = relationship(back_populates="entries")

    def __repr__(self) -> str:
        return (
            f"<AnimeEntry mal_id={self.mal_anime_id} title={self.title!r} "
            f"score={self.user_score} status={self.watch_status!r}>"
        )


class UserPreferenceProfile(Base):
    """Computed taste profile derived from a user's anime list.

    The ``profile_data`` column holds a JSON document with the full
    preference analysis.  Keeping it as JSON lets us iterate on the
    profile schema without database migrations — the LLM consumes it
    as a single document anyway.

    Example profile_data structure::

        {
            "total_watched": 142,
            "mean_score": 7.3,
            "score_distribution": {"10": 5, "9": 12, ...},
            "genre_affinity": {
                "Action": {"count": 45, "avg_score": 7.8},
                "Romance": {"count": 22, "avg_score": 6.9},
                ...
            },
            "theme_affinity": { ... },
            "studio_affinity": { ... },
            "preferred_formats": {"TV": 100, "Movie": 30, ...},
            "completion_rate": 0.85,
            "top_10": [ ... ],
            "watch_era_preference": {"2020s": 40, "2010s": 60, ...},
        }
    """

    __tablename__ = "user_preference_profiles"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    # ── The computed profile ─────────────────────────────
    profile_data: Mapped[dict] = mapped_column(JSON, default=dict)

    # ── Metadata ─────────────────────────────────────────
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    anime_count: Mapped[int] = mapped_column(
        Integer, default=0
    )  # how many entries were analysed

    # ── Timestamps ───────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<UserPreferenceProfile user_id={self.user_id!r} "
            f"anime_count={self.anime_count}>"
        )
