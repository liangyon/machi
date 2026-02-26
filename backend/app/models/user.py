"""User ORM model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class User(Base):
    """Application user — supports both OAuth and email/password sign-in."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # ── Auth provider ────────────────────────────────────
    provider: Mapped[str] = mapped_column(String(20))  # "google" | "discord" | "email"
    provider_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # unique ID from OAuth provider; null for email users

    # ── Email/password auth ──────────────────────────────
    hashed_password: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # null for OAuth-only users
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Timestamps ───────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r} provider={self.provider!r}>"
