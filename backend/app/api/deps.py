"""FastAPI dependency injection helpers."""

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import User
from app.services.auth import decode_access_token

COOKIE_NAME = "session"


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session, ensuring it is closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Extract user from the session cookie. Raises 401 if invalid/missing."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Like ``get_current_user`` but returns ``None`` for anonymous requests."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    try:
        payload = decode_access_token(token)
    except Exception:
        return None

    user_id: str | None = payload.get("sub")
    if not user_id:
        return None

    return db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
