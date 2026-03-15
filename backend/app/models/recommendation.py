"""Recommendation persistence models — Phase 3.5.

These models turn recommendations from ephemeral in-memory data into
durable database records.  This enables three key capabilities:

1. **Survival** — Recommendations survive server restarts.  Users come
   back and see their last generated recommendations immediately.

2. **History** — Users can browse past recommendation sessions ("what
   did it suggest yesterday when I asked for dark thrillers?").

3. **Feedback loop** — User feedback (👍/👎/✅) is persisted and used
   to tune future recommendations.  This is what turns a static tool
   into a *learning* recommendation engine.

Design notes
────────────
• **RecommendationSession** is the "header" — one row per "Generate"
  click.  It stores metadata about the generation event (when, what
  query, whether fallback was used).  Think of it like an invoice
  header — it groups the individual line items.

• **RecommendationEntry** is the "detail" — one row per recommended
  anime within a session.  We denormalise anime metadata (title,
  genres, etc.) intentionally: the recommendation was generated for
  *this snapshot* of the data.  If the catalog updates later, old
  recommendations should still display correctly.

• **RecommendationFeedback** stores user reactions to recommendations.
  We store genres/themes alongside the feedback so we can compute
  preference adjustments without joining back to the catalog table.
  This is a classic storage-vs-latency trade-off: disk is cheap,
  extra queries on every recommendation generation are not.

Relationship to existing models
───────────────────────────────
• Session → User: many-to-one (a user can have many sessions)
• Session → Entry: one-to-many (a session has many recommendations)
• Feedback → User: many-to-one (a user can give many feedbacks)
• Feedback is NOT linked to a session — it's per-anime, per-user.
  A user might see the same anime in multiple sessions and their
  feedback applies globally, not per-session.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    Float,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RecommendationSession(Base):
    """A single recommendation generation event.

    Created every time a user clicks "Generate Recommendations".
    Groups the individual ``RecommendationEntry`` rows that were
    produced in that generation.

    This is the "header" in the header/detail pattern — same as
    how ``AnimeList`` groups ``AnimeEntry`` rows.
    """

    __tablename__ = "recommendation_sessions"

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

    # ── Generation metadata ──────────────────────────────
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    custom_query: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # the custom query used, if any (e.g. "dark psychological thrillers")
    used_fallback: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # True if LLM failed and deterministic fallback was used
    total_count: Mapped[int] = mapped_column(
        Integer, default=0
    )  # how many recommendations were generated

    # ── Timestamps ───────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────
    entries: Mapped[list["RecommendationEntry"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",  # eager-load entries when we fetch a session
    )

    def __repr__(self) -> str:
        return (
            f"<RecommendationSession id={self.id!r} user_id={self.user_id!r} "
            f"total={self.total_count} query={self.custom_query!r}>"
        )


class RecommendationEntry(Base):
    """A single anime recommendation within a session.

    Stores everything the frontend needs to render a recommendation
    card: anime metadata, AI reasoning, confidence, and retriever
    scores.

    Why denormalise metadata?
    ─────────────────────────
    We store title, genres, synopsis, etc. even though they exist in
    ``AnimeCatalogEntry``.  This is intentional:

    1. The recommendation's reasoning was written for THIS version of
       the anime's data.  If the catalog updates, old recommendations
       should still make sense.

    2. We can render recommendation cards with a single query (load
       session + entries) instead of joining to the catalog table.

    3. The recommendation is a *historical record* — it should be
       immutable once created.
    """

    __tablename__ = "recommendation_entries"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # ── Parent session ───────────────────────────────────
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("recommendation_sessions.id", ondelete="CASCADE"),
        index=True,
    )

    # ── Anime identity ───────────────────────────────────
    mal_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(512))
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # ── Anime metadata (denormalised snapshot) ───────────
    genres: Mapped[str | None] = mapped_column(Text, nullable=True)
    themes: Mapped[str | None] = mapped_column(Text, nullable=True)
    synopsis: Mapped[str | None] = mapped_column(Text, nullable=True)
    mal_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anime_type: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── AI-generated fields ──────────────────────────────
    reasoning: Mapped[str] = mapped_column(
        Text, default="No reasoning provided."
    )
    confidence: Mapped[str] = mapped_column(
        String(10), default="medium"
    )  # high | medium | low
    similar_to: Mapped[list] = mapped_column(
        JSON, default=list
    )  # list of title strings from user's watched list

    # ── Retriever scores (for transparency/debugging) ────
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    preference_score: Mapped[float] = mapped_column(Float, default=0.0)
    combined_score: Mapped[float] = mapped_column(Float, default=0.0)

    # ── Fallback flag ────────────────────────────────────
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Timestamps ───────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ────────────────────────────────────
    session: Mapped["RecommendationSession"] = relationship(
        back_populates="entries"
    )

    def __repr__(self) -> str:
        return (
            f"<RecommendationEntry mal_id={self.mal_id} title={self.title!r} "
            f"confidence={self.confidence!r}>"
        )


class RecommendationFeedback(Base):
    """User feedback on a recommended anime.

    Stores 👍 (liked), 👎 (disliked), or ✅ (watched) reactions.
    This feedback is used in two ways:

    1. **Preference tuning** — "liked" boosts genre/theme affinity,
       "disliked" reduces it.  Applied as adjustments on top of the
       base preference profile.

    2. **Retrieval filtering** — "disliked" anime are excluded from
       future candidate retrieval.  "watched" anime are added to the
       exclusion set alongside the MAL watch list.

    Why store genres/themes here?
    ─────────────────────────────
    When computing preference adjustments, we need to know WHAT genres
    the liked/disliked anime belongs to.  Storing them here avoids a
    join to the catalog table on every recommendation generation.
    Storage is cheap; latency on the hot path is not.

    Why NOT linked to a session?
    ────────────────────────────
    Feedback is per-anime, per-user — not per-session.  If the same
    anime appears in multiple sessions, the user's opinion of it is
    the same regardless of which session they saw it in.  We use a
    unique constraint on (user_id, mal_id) so each anime has at most
    one feedback per user (the latest one wins).
    """

    __tablename__ = "recommendation_feedback"

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

    # ── What anime and what feedback ─────────────────────
    mal_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    feedback_type: Mapped[str] = mapped_column(
        String(20)
    )  # liked | disliked | watched

    # ── Anime metadata for preference adjustment ─────────
    # Stored here so we can compute genre/theme boosts without
    # joining to the catalog table.
    genres: Mapped[str | None] = mapped_column(Text, nullable=True)
    themes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Timestamps ───────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<RecommendationFeedback user_id={self.user_id!r} "
            f"mal_id={self.mal_id} feedback={self.feedback_type!r}>"
        )
