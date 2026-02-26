"""User-related Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Payload for email/password registration."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str | None = None


class LoginRequest(BaseModel):
    """Payload for email/password login."""

    email: EmailStr
    password: str


class UserRead(BaseModel):
    """Public representation of a user (returned by /auth/me)."""

    id: str
    email: str
    name: str | None
    avatar_url: str | None
    provider: str
    created_at: datetime

    model_config = {"from_attributes": True}
