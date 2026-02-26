"""Authentication routes — OAuth (Google, Discord) + email/password."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.models.user import User
from app.schemas.user import LoginRequest, RegisterRequest, UserRead
from app.services.auth import (
    SUPPORTED_PROVIDERS,
    create_access_token,
    hash_password,
    oauth,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "session"
COOKIE_MAX_AGE = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # seconds


def _set_session_cookie(response: Response, user_id: str) -> None:
    """Create a JWT and set it as an HttpOnly cookie on *response*."""
    token = create_access_token(user_id)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=not settings.DEBUG,  # Secure in production
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


# ── Email / password ────────────────────────────────────


@router.post("/register", response_model=UserRead)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> User:
    """Create a new account with email + password."""
    existing = db.execute(
        select(User).where(User.email == body.email)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        provider="email",
        hashed_password=hash_password(body.password),
        is_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> UserRead:
    """Authenticate with email + password and set a session cookie."""
    user = db.execute(
        select(User).where(User.email == body.email, User.provider == "email")
    ).scalar_one_or_none()

    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _set_session_cookie(response, user.id)
    return UserRead.model_validate(user)


# ── OAuth ────────────────────────────────────────────────


@router.get("/{provider}/login")
async def oauth_login(provider: str, request: Request):
    """Redirect browser to the OAuth provider's authorize page."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unsupported provider: {provider}")

    client = oauth.create_client(provider)
    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback", name="oauth_callback")
async def oauth_callback(
    provider: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback, upsert user, set cookie, redirect to frontend."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unsupported provider: {provider}")

    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)

    # ── Extract user info from the provider ──────────────
    if provider == "google":
        # Google returns an id_token with user info
        user_info = token.get("userinfo") or await client.userinfo(token=token)
        provider_id = user_info["sub"]
        email = user_info["email"]
        name = user_info.get("name")
        avatar_url = user_info.get("picture")

    elif provider == "discord":
        resp = await client.get("users/@me", token=token)
        user_info = resp.json()
        provider_id = user_info["id"]
        email = user_info.get("email")
        name = user_info.get("username")
        avatar_hash = user_info.get("avatar")
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{provider_id}/{avatar_hash}.png"
            if avatar_hash
            else None
        )

    if not email:
        raise HTTPException(
            status_code=400,
            detail="Could not retrieve email from provider",
        )

    # ── Upsert user ──────────────────────────────────────
    user = db.execute(
        select(User).where(User.provider == provider, User.provider_id == provider_id)
    ).scalar_one_or_none()

    if user:
        # Update mutable fields
        user.name = name
        user.avatar_url = avatar_url
        user.email = email
    else:
        # Check if email is already taken by another provider
        email_user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if email_user:
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists. Please log in with your original method.",
            )
        user = User(
            email=email,
            name=name,
            avatar_url=avatar_url,
            provider=provider,
            provider_id=provider_id,
            is_verified=True,  # OAuth emails are considered verified
        )
        db.add(user)

    db.commit()
    db.refresh(user)

    # ── Set cookie & redirect to frontend ────────────────
    redirect = RedirectResponse(url=settings.FRONTEND_URL, status_code=302)
    _set_session_cookie(redirect, user.id)
    return redirect


# ── Session endpoints ────────────────────────────────────


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return current_user


@router.post("/logout")
def logout(response: Response) -> dict:
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"detail": "Logged out"}
