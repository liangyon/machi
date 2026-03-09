"""MAL import and preference profile API endpoints.

This module is the "glue" between the frontend and our MAL/preference
services.  It handles:

1. Request validation (via Pydantic schemas)
2. Authentication (via ``get_current_user`` dependency)
3. Orchestration (coordinates MAL service → DB → preference analyser)
4. Response shaping (returns data in the format the frontend expects)

The import endpoint uses FastAPI's ``BackgroundTasks`` to return a
response immediately ("import started!") while the MAL API fetching
happens in the background.  This avoids the frontend waiting for a
large list.  In Phase 4 we'll upgrade to a proper job queue
(arq/Celery), but BackgroundTasks is perfect for dev — it runs in
the same process with zero infrastructure.

Since we switched to the official MAL API v2, the import is now much
simpler — we get all metadata (genres, synopsis, studios, etc.) in a
single paginated call.  No more two-pass enrichment.
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
    AnimeEntryResponse,
    AnimeListResponse,
    MALImportRequest,
    MALImportResponse,
    MALSyncStatus,
    PreferenceProfileResponse,
)
from app.services.mal import (
    fetch_user_animelist,
    parse_mal_animelist_entry,
)
from app.services.preference_analyzer import analyze_preferences

router = APIRouter(prefix="/mal", tags=["MAL"])


# ── POST /api/mal/import ─────────────────────────────────


@router.post("/import", response_model=MALImportResponse)
async def import_mal_list(
    body: MALImportRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start importing a user's MAL anime list.

    This endpoint returns immediately with a "pending" status.
    The actual fetching happens in the background via FastAPI's
    BackgroundTasks.  Poll ``GET /api/mal/status`` to track progress.

    If the user already has an imported list, it will be replaced
    (idempotent re-import).
    """
    mal_username = body.mal_username.strip()

    # Check if user already has a list — reuse or create
    anime_list = db.execute(
        select(AnimeList).where(AnimeList.user_id == user.id)
    ).scalar_one_or_none()

    if anime_list:
        # Reset for re-import: clear old entries, update username
        anime_list.mal_username = mal_username
        anime_list.sync_status = "pending"
        anime_list.total_entries = 0
        # Delete old entries (cascade would handle this, but explicit is clearer)
        db.execute(
            AnimeEntry.__table__.delete().where(
                AnimeEntry.anime_list_id == anime_list.id
            )
        )
    else:
        anime_list = AnimeList(
            user_id=user.id,
            mal_username=mal_username,
            sync_status="pending",
        )
        db.add(anime_list)

    db.commit()
    db.refresh(anime_list)

    # Kick off the import in the background
    background_tasks.add_task(
        _run_import, anime_list.id, user.id, mal_username
    )

    return MALImportResponse(
        anime_list_id=anime_list.id,
        mal_username=mal_username,
        sync_status="pending",
        message=f"Import started for MAL user '{mal_username}'. Poll /api/mal/status for progress.",
    )


# ── GET /api/mal/status ──────────────────────────────────


@router.get("/status", response_model=MALSyncStatus)
def get_sync_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Check the status of the user's MAL import.

    Returns the current sync status, total entries imported, and
    when the last sync completed.
    """
    anime_list = db.execute(
        select(AnimeList).where(AnimeList.user_id == user.id)
    ).scalar_one_or_none()

    if not anime_list:
        raise HTTPException(
            status_code=404,
            detail="No MAL list found. Import one first via POST /api/mal/import.",
        )

    return MALSyncStatus(
        anime_list_id=anime_list.id,
        mal_username=anime_list.mal_username,
        sync_status=anime_list.sync_status,
        total_entries=anime_list.total_entries,
        last_synced_at=anime_list.last_synced_at,
    )


# ── GET /api/mal/list ────────────────────────────────────


@router.get("/list", response_model=AnimeListResponse)
def get_anime_list(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's full imported anime list with all entries."""
    anime_list = db.execute(
        select(AnimeList).where(AnimeList.user_id == user.id)
    ).scalar_one_or_none()

    if not anime_list:
        raise HTTPException(
            status_code=404,
            detail="No MAL list found. Import one first.",
        )

    return AnimeListResponse(
        mal_username=anime_list.mal_username,
        sync_status=anime_list.sync_status,
        total_entries=anime_list.total_entries,
        last_synced_at=anime_list.last_synced_at,
        entries=[AnimeEntryResponse.model_validate(e) for e in anime_list.entries],
    )


# ── GET /api/mal/profile ─────────────────────────────────


@router.get("/profile", response_model=PreferenceProfileResponse)
def get_preference_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's computed preference profile.

    The profile is generated automatically after a successful MAL
    import.  If no profile exists yet, returns 404.
    """
    profile = db.execute(
        select(UserPreferenceProfile).where(
            UserPreferenceProfile.user_id == user.id
        )
    ).scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="No preference profile found. Import your MAL list first.",
        )

    # The profile_data JSON blob matches PreferenceProfileResponse
    return PreferenceProfileResponse(**profile.profile_data)


# ── Background import task ───────────────────────────────


async def _run_import(
    anime_list_id: str,
    user_id: str,
    mal_username: str,
) -> None:
    """Background task that performs the actual MAL import.

    This runs after the endpoint has already returned a response.
    It uses its own DB session (background tasks run outside the
    request lifecycle, so the request's session is already closed).

    Since we use the official MAL API v2, we get all metadata in a
    single paginated call — no more two-pass enrichment.

    Steps:
    1. Fetch the user's animelist from MAL API v2 (paginated, with fields)
    2. Parse each entry into our normalised format
    3. Save all entries to the database
    4. Run the preference analyser and save the profile
    5. Update sync status to "completed"
    """
    from app.db.session import SessionLocal

    db = SessionLocal()

    try:
        # Mark as in_progress
        anime_list = db.get(AnimeList, anime_list_id)
        if not anime_list:
            logger.error("AnimeList %s not found for import", anime_list_id)
            return

        anime_list.sync_status = "in_progress"
        db.commit()

        # ── Step 1: Fetch animelist from MAL API v2 ──────
        logger.info("Starting import for MAL user: %s", mal_username)
        raw_entries = await fetch_user_animelist(mal_username)

        if not raw_entries:
            anime_list.sync_status = "completed"
            anime_list.total_entries = 0
            anime_list.last_synced_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("MAL user %s has an empty list", mal_username)
            return

        # ── Step 2: Parse entries (all metadata included!) ─
        parsed = [parse_mal_animelist_entry(raw) for raw in raw_entries]
        # Filter out entries without a valid MAL ID
        parsed = [p for p in parsed if p.get("mal_anime_id")]

        logger.info("Parsed %d entries from MAL API", len(parsed))

        # ── Step 3: Create and save AnimeEntry records ───
        entries = []
        for p in parsed:
            entry = AnimeEntry(
                anime_list_id=anime_list_id,
                **p,
            )
            entries.append(entry)

        db.add_all(entries)

        # Update list metadata
        anime_list.total_entries = len(entries)
        anime_list.last_synced_at = datetime.now(timezone.utc)
        anime_list.sync_status = "completed"
        db.commit()

        logger.info(
            "Saved %d entries for MAL user %s", len(entries), mal_username
        )

        # ── Step 4: Generate preference profile ──────────
        # Re-query entries from DB to get proper ORM objects
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

        # Upsert preference profile
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
        logger.info("Preference profile generated for user %s", user_id)

    except ValueError as exc:
        # MAL user not found, private list, etc.
        logger.warning("Import failed for %s: %s", mal_username, exc)
        anime_list = db.get(AnimeList, anime_list_id)
        if anime_list:
            anime_list.sync_status = "failed"
            db.commit()

    except RuntimeError as exc:
        # MAL_CLIENT_ID not configured or invalid
        logger.error("Import config error for %s: %s", mal_username, exc)
        anime_list = db.get(AnimeList, anime_list_id)
        if anime_list:
            anime_list.sync_status = "failed"
            db.commit()

    except Exception as exc:
        logger.exception("Unexpected error during import for %s", mal_username)
        anime_list = db.get(AnimeList, anime_list_id)
        if anime_list:
            anime_list.sync_status = "failed"
            db.commit()

    finally:
        db.close()
