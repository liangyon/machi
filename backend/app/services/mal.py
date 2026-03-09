"""MAL (MyAnimeList) ingestion service via the official MAL API v2.

Uses the official MAL API (https://api.myanimelist.net/v2) for fetching
user anime lists, and Jikan (https://jikan.moe/) as a fallback for
additional anime detail lookups if needed.

Why the official MAL API instead of Jikan?
──────────────────────────────────────────
Jikan's ``/users/{username}/animelist`` endpoint is deprecated.  The
official MAL API v2 is the supported way to fetch user lists.  It also
has a major advantage: we can request rich metadata (genres, synopsis,
studios, etc.) directly in the animelist response via the ``fields``
parameter.  This eliminates the need for a second pass of detail
fetches — one API call per page gives us everything.

Key design decisions
────────────────────
1. **Authentication** — The MAL API requires a Client ID sent via the
   ``X-MAL-CLIENT-ID`` header.  No user OAuth needed for reading
   public lists.  The Client ID is stored in ``.env``.

2. **Rate limiting** — MAL API allows ~1 req/s for free tier.  We use
   ``asyncio.sleep`` between paginated requests.

3. **Rich fields in one pass** — By requesting ``fields=list_status,
   genres,synopsis,...`` we get all metadata in the animelist response.
   No need for separate ``/anime/{id}`` calls.

4. **Pagination** — MAL API uses ``offset`` + ``limit`` (max 1000 per
   page, but we use 100 for safety).  It provides a ``next`` URL in
   the ``paging`` object.

5. **Jikan fallback** — We keep Jikan for anime detail lookups in case
   we need data the MAL API doesn't provide (e.g. for the anime
   catalog in Phase 2).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.core.logging import logger

# ── API constants ────────────────────────────────────────

MAL_API_BASE = "https://api.myanimelist.net/v2"
JIKAN_BASE = "https://api.jikan.moe/v4"

# Fields we request from the MAL API animelist endpoint.
# This gives us rich metadata in a single call — no second pass needed.
MAL_ANIMELIST_FIELDS = ",".join([
    "list_status",
    "num_episodes",
    "status",           # airing status
    "media_type",       # tv, movie, ova, etc.
    "genres",
    "synopsis",
    "studios",
    "start_season",
    "mean",             # community score
    "num_list_users",   # popularity
    "alternative_titles",
    "main_picture",
])

MAL_PAGE_LIMIT = 100  # entries per page (max 1000, but 100 is safer)
MAL_RATE_LIMIT_DELAY = 1.0  # seconds between requests (~1 req/s for free tier)
JIKAN_RATE_LIMIT_DELAY = 0.4  # Jikan allows ~3 req/s


# ── Public interface ─────────────────────────────────────


async def fetch_user_animelist(mal_username: str) -> list[dict]:
    """Fetch a user's complete anime list from the official MAL API v2.

    Returns a list of raw MAL API animelist entries (dicts).
    Handles pagination automatically.

    Requires ``MAL_CLIENT_ID`` to be set in the environment.

    Raises ``ValueError`` if the MAL username is not found.
    Raises ``RuntimeError`` if MAL_CLIENT_ID is not configured.
    Raises ``httpx.HTTPStatusError`` on unexpected API errors.
    """
    if not settings.MAL_CLIENT_ID:
        raise RuntimeError(
            "MAL_CLIENT_ID is not configured. "
            "Register at https://myanimelist.net/apiconfig and add it to .env"
        )

    entries: list[dict] = []
    offset = 0

    headers = {
        "X-MAL-CLIENT-ID": settings.MAL_CLIENT_ID,
    }

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        while True:
            url = f"{MAL_API_BASE}/users/{mal_username}/animelist"
            params = {
                "fields": MAL_ANIMELIST_FIELDS,
                "limit": MAL_PAGE_LIMIT,
                "offset": offset,
                "nsfw": "true",  # include all entries, not just SFW
            }

            logger.info(
                "Fetching MAL animelist for %s — offset %d", mal_username, offset
            )

            resp = await client.get(url, params=params)

            # Handle common errors
            if resp.status_code == 404:
                raise ValueError(f"MAL user '{mal_username}' not found.")
            if resp.status_code == 403:
                raise ValueError(
                    f"MAL user '{mal_username}' has a private anime list."
                )
            if resp.status_code == 429:
                logger.warning("MAL API rate limit hit, backing off 3s…")
                await asyncio.sleep(3.0)
                continue
            if resp.status_code == 401:
                raise RuntimeError(
                    "MAL API returned 401 — check your MAL_CLIENT_ID is valid."
                )
            resp.raise_for_status()

            data = resp.json()
            page_entries = data.get("data", [])
            entries.extend(page_entries)

            # Check if there are more pages
            paging = data.get("paging", {})
            next_url = paging.get("next")

            logger.info(
                "Offset %d: got %d entries (total so far: %d, has_next: %s)",
                offset, len(page_entries), len(entries), bool(next_url),
            )

            if not next_url or not page_entries:
                break

            offset += MAL_PAGE_LIMIT
            await asyncio.sleep(MAL_RATE_LIMIT_DELAY)

    logger.info(
        "Finished fetching animelist for %s — %d total entries",
        mal_username, len(entries),
    )
    return entries


async def fetch_anime_details_jikan(mal_anime_id: int) -> dict | None:
    """Fetch full details for a single anime from Jikan (fallback).

    Returns the anime data dict, or ``None`` if the fetch fails.
    Used when we need data the MAL API doesn't provide.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            url = f"{JIKAN_BASE}/anime/{mal_anime_id}"
            resp = await client.get(url)

            if resp.status_code == 429:
                logger.warning("Jikan rate limited on anime/%d, backing off…", mal_anime_id)
                await asyncio.sleep(2.0)
                resp = await client.get(url)

            if resp.status_code == 404:
                logger.warning("Anime %d not found on Jikan (deleted?)", mal_anime_id)
                return None

            resp.raise_for_status()
            return resp.json().get("data")

        except Exception as exc:
            logger.warning(
                "Failed to fetch Jikan details for anime %d: %s", mal_anime_id, exc
            )
            return None


# ── MAL API response parsing ────────────────────────────


def parse_mal_animelist_entry(raw: dict) -> dict:
    """Parse a raw MAL API v2 animelist entry into our normalised format.

    The MAL API v2 ``/users/{name}/animelist`` returns entries like::

        {
            "node": {
                "id": 1,
                "title": "Cowboy Bebop",
                "main_picture": {"medium": "...", "large": "..."},
                "num_episodes": 26,
                "status": "finished_airing",
                "media_type": "tv",
                "genres": [{"id": 1, "name": "Action"}, ...],
                "synopsis": "...",
                "studios": [{"id": 14, "name": "Sunrise"}],
                "start_season": {"year": 1998, "season": "spring"},
                "mean": 8.75,
                "num_list_users": 1500000,
                "alternative_titles": {"en": "Cowboy Bebop", ...}
            },
            "list_status": {
                "status": "completed",
                "score": 9,
                "num_episodes_watched": 26,
                "updated_at": "2023-01-01T00:00:00+00:00"
            }
        }
    """
    node = raw.get("node", {})
    list_status = raw.get("list_status", {})

    # Map MAL API status strings to our internal values
    status_map = {
        "watching": "watching",
        "completed": "completed",
        "on_hold": "on_hold",
        "dropped": "dropped",
        "plan_to_watch": "plan_to_watch",
    }
    watch_status = status_map.get(
        list_status.get("status", ""), list_status.get("status", "unknown")
    )

    # Extract image URL
    main_picture = node.get("main_picture", {})
    image_url = main_picture.get("large") or main_picture.get("medium")

    # Extract genres as comma-separated string
    genres_list = node.get("genres", [])
    genres = ", ".join(g["name"] for g in genres_list) if genres_list else None

    # Extract studios as comma-separated string
    studios_list = node.get("studios", [])
    studios = ", ".join(s["name"] for s in studios_list) if studios_list else None

    # Extract season/year
    start_season = node.get("start_season", {})
    season = start_season.get("season")
    year = start_season.get("year")

    # Extract English title
    alt_titles = node.get("alternative_titles", {})
    title_english = alt_titles.get("en")

    # Map media_type to our format
    media_type_map = {
        "tv": "TV",
        "movie": "Movie",
        "ova": "OVA",
        "ona": "ONA",
        "special": "Special",
        "music": "Music",
        "unknown": None,
    }
    anime_type = media_type_map.get(node.get("media_type", ""), node.get("media_type"))

    # Map airing status
    airing_status_map = {
        "finished_airing": "Finished Airing",
        "currently_airing": "Currently Airing",
        "not_yet_aired": "Not yet aired",
    }
    anime_status = airing_status_map.get(node.get("status", ""), node.get("status"))

    return {
        "mal_anime_id": node.get("id"),
        "title": node.get("title", "Unknown"),
        "title_english": title_english,
        "image_url": image_url,
        "watch_status": watch_status,
        "user_score": list_status.get("score", 0) or 0,
        "episodes_watched": list_status.get("num_episodes_watched", 0) or 0,
        "total_episodes": node.get("num_episodes"),
        "anime_type": anime_type,
        "anime_status": anime_status,
        "synopsis": node.get("synopsis"),
        "genres": genres,
        "themes": None,  # MAL API doesn't have themes; we can enrich via Jikan later
        "studios": studios,
        "season": f"{season}" if season else None,
        "year": year,
        "mal_score": node.get("mean"),
        "mal_members": node.get("num_list_users"),
    }


# ── Jikan response parsing (kept for fallback/Phase 2) ──


def parse_jikan_anime_details(detail: dict) -> dict:
    """Extract rich metadata from a Jikan ``/anime/{id}`` response.

    Useful for getting themes and other data the MAL API doesn't provide.
    """
    return {
        "synopsis": detail.get("synopsis"),
        "genres": _extract_names(detail.get("genres", [])),
        "themes": _extract_names(detail.get("themes", [])),
        "studios": _extract_names(detail.get("studios", [])),
        "season": detail.get("season"),
        "year": detail.get("year"),
        "mal_score": detail.get("score"),
        "mal_members": detail.get("members"),
        "total_episodes": detail.get("episodes"),
        "anime_type": detail.get("type"),
        "anime_status": detail.get("status"),
    }


# ── Private helpers ──────────────────────────────────────


def _extract_names(items: list[dict]) -> str | None:
    """Extract a comma-separated string of names from Jikan's
    ``[{"mal_id": 1, "name": "Action"}, ...]`` format.
    """
    if not items:
        return None
    return ", ".join(item["name"] for item in items if "name" in item)


def _extract_image_url(anime_data: dict) -> str | None:
    """Pull the best available image URL from Jikan's nested images object."""
    images = anime_data.get("images", {})
    jpg = images.get("jpg", {})
    return jpg.get("large_image_url") or jpg.get("image_url")
