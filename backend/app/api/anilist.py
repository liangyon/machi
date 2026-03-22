"""AniList import and preference profile API endpoints.

Mirrors the structure of ``app/api/mal.py``.  The key difference in the
import flow is that AniList entries are **upserted** by ``mal_anime_id``
rather than deleting and re-inserting all entries.  This allows MAL and
AniList imports to coexist in the same ``AnimeList`` row — entries from
both sources are merged by ``mal_anime_id``.

Entries where ``idMal`` is null (AniList-exclusive titles) are skipped and
counted in the import response.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.logging import logger
from app.models.anime import AnimeEntry, AnimeList, UserPreferenceProfile
from app.models.user import User
from app.schemas.anime import (
    AniListImportRequest,
    AniListImportResponse,
    AniListSyncStatus,
)
from app.services.anilist import fetch_user_animelist_anilist
from app.services.preference_analyzer import analyze_preferences

router = APIRouter(prefix="/anilist", tags=["AniList"])


# ── POST /api/anilist/import ──────────────────────────────


@router.post("/import", response_model=AniListImportResponse)
async def import_anilist_list(
    body: AniListImportRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start importing a user's AniList anime list.

    Returns immediately with a "pending" status.  The actual fetching
    happens in the background.  Poll ``GET /api/anilist/status`` to
    track progress.

    AniList and MAL imports share the same ``AnimeList`` row (one per
    user).  AniList entries are upserted by ``mal_anime_id`` so both
    sources can coexist.
    """
    anilist_username = body.anilist_username.strip()

    # Check if user already has a list — reuse or create
    anime_list = db.execute(
        select(AnimeList).where(AnimeList.user_id == user.id)
    ).scalar_one_or_none()

    if anime_list:
        # Update anilist_username and source; preserve existing entries
        anime_list.anilist_username = anilist_username
        anime_list.source = "anilist"
        anime_list.sync_status = "pending"
    else:
        anime_list = AnimeList(
            user_id=user.id,
            anilist_username=anilist_username,
            mal_username=None,
            source="anilist",
            sync_status="pending",
        )
        db.add(anime_list)

    db.commit()
    db.refresh(anime_list)

    background_tasks.add_task(
        _run_anilist_import, anime_list.id, user.id, anilist_username
    )

    return AniListImportResponse(
        anime_list_id=anime_list.id,
        anilist_username=anilist_username,
        sync_status="pending",
        message=f"Import started for AniList user '{anilist_username}'. Poll /api/anilist/status for progress.",
    )


# ── GET /api/anilist/status ───────────────────────────────


@router.get("/status", response_model=AniListSyncStatus)
def get_anilist_sync_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check the status of the user's AniList import."""
    anime_list = db.execute(
        select(AnimeList).where(AnimeList.user_id == user.id)
    ).scalar_one_or_none()

    if not anime_list or not anime_list.anilist_username:
        raise HTTPException(
            status_code=404,
            detail="No AniList import found. Import one first via POST /api/anilist/import.",
        )

    return AniListSyncStatus(
        anime_list_id=anime_list.id,
        anilist_username=anime_list.anilist_username,
        sync_status=anime_list.sync_status,
        total_entries=anime_list.total_entries,
        skipped_no_mal_id=0,  # not persisted; reported in logs
        last_synced_at=anime_list.last_synced_at,
    )


# ── Background import task ────────────────────────────────


async def _run_anilist_import(
    anime_list_id: str,
    user_id: str,
    anilist_username: str,
) -> None:
    """Background task that performs the actual AniList import.

    Uses its own DB session (background tasks run outside the request
    lifecycle — the request session is already closed by the time this runs).

    Unlike the MAL import (which deletes + re-inserts all entries),
    this upserts by ``mal_anime_id`` so existing MAL entries are
    preserved and merged with AniList data.

    Steps:
    1. Mark list as in_progress
    2. Fetch animelist from AniList GraphQL API
    3. Parse + filter entries (skip nullidMal)
    4. Delete existing entries, bulk-insert fresh AnimeEntry rows
    5. Update list metadata and mark completed
    6. Generate / update preference profile
    """
    from app.db.session import SessionLocal

    db = SessionLocal()

    try:
        anime_list = db.get(AnimeList, anime_list_id)
        if not anime_list:
            logger.error("AnimeList %s not found for AniList import", anime_list_id)
            return

        anime_list.sync_status = "in_progress"
        db.commit()

        # ── Step 1: Fetch from AniList ────────────────
        logger.info("Starting AniList import for user: %s", anilist_username)
        parsed_entries, skipped = await fetch_user_animelist_anilist(anilist_username)

        logger.info(
            "AniList fetch complete: %d entries, %d skipped (no idMal)",
            len(parsed_entries),
            skipped,
        )

        if not parsed_entries:
            anime_list.sync_status = "completed"
            anime_list.total_entries = 0
            anime_list.last_synced_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("AniList user %s has an empty list", anilist_username)
            return

        # ── Step 2: Delete existing entries, then bulk-insert fresh ─
        # Same approach as MAL import — ensures stale entries (shows
        # removed from the user's AniList) are properly deleted.
        db.execute(
            AnimeEntry.__table__.delete().where(
                AnimeEntry.anime_list_id == anime_list_id
            )
        )

        entries = [AnimeEntry(anime_list_id=anime_list_id, **p) for p in parsed_entries]
        db.add_all(entries)

        # Update list metadata
        anime_list.total_entries = len(entries)
        anime_list.last_synced_at = datetime.now(timezone.utc)
        anime_list.sync_status = "completed"
        db.commit()

        logger.info(
            "AniList import complete for %s: %d entries saved",
            anilist_username,
            len(entries),
        )

        # ── Step 4: Generate preference profile ──────
        db_entries = (
            db.execute(
                select(AnimeEntry).where(
                    AnimeEntry.anime_list_id == anime_list_id
                )
            )
            .scalars()
            .all()
        )

        profile_data = analyze_preferences(list(db_entries))

        profile = db.execute(
            select(UserPreferenceProfile).where(
                UserPreferenceProfile.user_id == user_id
            )
        ).scalar_one_or_none()

        if profile:
            profile.profile_data = profile_data
            profile.anime_count = len(db_entries)
            profile.generated_at = datetime.now(timezone.utc)
        else:
            profile = UserPreferenceProfile(
                user_id=user_id,
                profile_data=profile_data,
                anime_count=len(db_entries),
            )
            db.add(profile)

        db.commit()
        logger.info("Preference profile updated for user %s (AniList import)", user_id)

    except ValueError as exc:
        logger.warning("AniList import failed for %s: %s", anilist_username, exc)
        anime_list = db.get(AnimeList, anime_list_id)
        if anime_list:
            anime_list.sync_status = "failed"
            db.commit()

    except Exception:
        logger.exception("Unexpected error during AniList import for %s", anilist_username)
        anime_list = db.get(AnimeList, anime_list_id)
        if anime_list:
            anime_list.sync_status = "failed"
            db.commit()

    finally:
        db.close()
