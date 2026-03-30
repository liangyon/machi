"""GET /api/taste-card — returns a personality summary of the user's anime taste."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.anime import AnimeList, UserPreferenceProfile
from app.models.user import User
from app.schemas.taste_card import TasteCardResponse
from app.services.taste_card import (
    compute_taste_card,
    get_cached_taste_card,
    invalidate_taste_card_cache,
    set_cached_taste_card,
)

router = APIRouter(prefix="/taste-card", tags=["Taste Card"])


@router.get("", response_model=TasteCardResponse)
def get_taste_card(
    refresh: bool = Query(default=False, description="Bypass cache and regenerate"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's Taste Card.

    Computed from the stored preference profile + anime entries.
    Results are cached in-process for 1 hour.  Pass ?refresh=true to
    force regeneration (e.g. after a list re-import).
    """
    if not refresh:
        cached = get_cached_taste_card(user.id)
        if cached:
            return TasteCardResponse(**cached)

    # Load preference profile
    profile = db.execute(
        select(UserPreferenceProfile).where(UserPreferenceProfile.user_id == user.id)
    ).scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="No preference profile found. Import your MAL or AniList list first.",
        )

    # Load anime list (entries are eager-loaded via selectin)
    anime_list = db.execute(
        select(AnimeList).where(AnimeList.user_id == user.id)
    ).scalar_one_or_none()

    entries = anime_list.entries if anime_list else []

    # Source badge metadata
    source = None
    imported_username = None
    if anime_list:
        source = anime_list.source
        imported_username = (
            anime_list.anilist_username
            if anime_list.source == "anilist"
            else anime_list.mal_username
        )

    card_data = compute_taste_card(profile.profile_data, entries)
    card_data["source"] = source
    card_data["imported_username"] = imported_username

    if not refresh:
        set_cached_taste_card(user.id, card_data)

    return TasteCardResponse(**card_data)


@router.delete("/cache", status_code=204)
def bust_taste_card_cache(user: User = Depends(get_current_user)):
    """Manually invalidate the cached taste card for the current user."""
    invalidate_taste_card_cache(user.id)
