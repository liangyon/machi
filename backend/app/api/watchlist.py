"""Watchlist API endpoints — user's to-watch list.

Endpoints:
- GET    /api/watchlist            — list all watchlist items
- POST   /api/watchlist            — add an anime to the watchlist
- PATCH  /api/watchlist/{mal_id}   — update status, rating, reaction
- DELETE /api/watchlist/{mal_id}   — remove an anime from the watchlist

The watchlist is independent from the feedback system. Users can:
- Add anime to their watchlist from recommendations (bookmark button)
- Update status (to_watch → watching → completed/dropped)
- Record their rating and reaction after watching
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.logging import logger
from app.models.user import User
from app.models.watchlist import WatchlistEntry
from app.schemas.watchlist import (
    WatchlistAddRequest,
    WatchlistAddResponse,
    WatchlistItemResponse,
    WatchlistRemoveResponse,
    WatchlistResponse,
    WatchlistUpdateRequest,
    WatchlistUpdateResponse,
)

router = APIRouter(prefix="/watchlist", tags=["Watchlist"])


def _entry_to_response(e: WatchlistEntry) -> WatchlistItemResponse:
    """Convert a WatchlistEntry ORM object to a response schema."""
    return WatchlistItemResponse(
        id=e.id,
        mal_id=e.mal_id,
        title=e.title,
        image_url=e.image_url,
        genres=e.genres,
        themes=e.themes,
        mal_score=e.mal_score,
        year=e.year,
        anime_type=e.anime_type,
        status=e.status,
        user_rating=e.user_rating,
        reaction=e.reaction,
        source=e.source,
        notes=e.notes,
        added_at=e.added_at,
    )


# ═════════════════════════════════════════════════════════
# GET /api/watchlist
# ═════════════════════════════════════════════════════════


@router.get("", response_model=WatchlistResponse)
def get_watchlist(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's full watchlist, sorted by most recently added."""
    entries = (
        db.execute(
            select(WatchlistEntry)
            .where(WatchlistEntry.user_id == user.id)
            .order_by(WatchlistEntry.added_at.desc())
        )
        .scalars()
        .all()
    )

    items = [_entry_to_response(e) for e in entries]
    return WatchlistResponse(items=items, total=len(items))


# ═════════════════════════════════════════════════════════
# POST /api/watchlist
# ═════════════════════════════════════════════════════════


@router.post("", response_model=WatchlistAddResponse)
def add_to_watchlist(
    body: WatchlistAddRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add an anime to the user's watchlist.

    If the anime is already on the watchlist, returns the existing
    entry with ``already_existed=True`` (idempotent).
    """
    existing = db.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user.id,
            WatchlistEntry.mal_id == body.mal_id,
        )
    ).scalar_one_or_none()

    if existing:
        return WatchlistAddResponse(
            item=_entry_to_response(existing),
            message="Already on your watchlist",
            already_existed=True,
        )

    entry = WatchlistEntry(
        user_id=user.id,
        mal_id=body.mal_id,
        title=body.title,
        image_url=body.image_url,
        genres=body.genres,
        themes=body.themes,
        mal_score=body.mal_score,
        year=body.year,
        anime_type=body.anime_type,
        source=body.source,
        notes=body.notes,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    logger.info(
        "Added to watchlist: user=%s, mal_id=%d, title=%s",
        user.id,
        body.mal_id,
        body.title,
    )

    return WatchlistAddResponse(
        item=_entry_to_response(entry),
        message="Added to your watchlist!",
        already_existed=False,
    )


# ═════════════════════════════════════════════════════════
# PATCH /api/watchlist/{mal_id}
# ═════════════════════════════════════════════════════════


@router.patch("/{mal_id}", response_model=WatchlistUpdateResponse)
def update_watchlist_entry(
    mal_id: int,
    body: WatchlistUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a watchlist entry's status, rating, or reaction.

    Use this to:
    - Change status: to_watch → watching → completed/dropped
    - Record a rating (1-10) after watching
    - Write a reaction/review after watching
    """
    entry = db.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user.id,
            WatchlistEntry.mal_id == mal_id,
        )
    ).scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Anime not found on your watchlist.",
        )

    # Apply updates (only non-None fields)
    if body.status is not None:
        entry.status = body.status
    if body.user_rating is not None:
        entry.user_rating = body.user_rating
    if body.reaction is not None:
        entry.reaction = body.reaction
    if body.notes is not None:
        entry.notes = body.notes

    db.commit()
    db.refresh(entry)

    logger.info(
        "Updated watchlist entry: user=%s, mal_id=%d, status=%s, rating=%s",
        user.id,
        mal_id,
        entry.status,
        entry.user_rating,
    )

    return WatchlistUpdateResponse(
        item=_entry_to_response(entry),
        message="Watchlist entry updated!",
    )


# ═════════════════════════════════════════════════════════
# DELETE /api/watchlist/{mal_id}
# ═════════════════════════════════════════════════════════


@router.delete("/{mal_id}", response_model=WatchlistRemoveResponse)
def remove_from_watchlist(
    mal_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove an anime from the user's watchlist."""
    entry = db.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user.id,
            WatchlistEntry.mal_id == mal_id,
        )
    ).scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Anime not found on your watchlist.",
        )

    db.delete(entry)
    db.commit()

    logger.info(
        "Removed from watchlist: user=%s, mal_id=%d",
        user.id,
        mal_id,
    )

    return WatchlistRemoveResponse(
        mal_id=mal_id,
        message="Removed from your watchlist.",
    )
