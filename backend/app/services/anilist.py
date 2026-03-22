"""AniList ingestion service via the AniList GraphQL API.

AniList provides a free, no-auth GraphQL API for reading public anime lists.
The key bridge to our existing infrastructure: every media entry returns
``idMal`` — the MyAnimeList ID.  This means AniList entries are normalized
into the same ``AnimeEntry`` rows the rest of the system already uses.

Key design decisions
────────────────────
1. **No authentication required** — AniList public lists are accessible
   without OAuth.  A single GraphQL POST is all we need.

2. **Single-query full list** — AniList returns the full list in one
   request (default chunk behaviour).  For very large lists (>500 entries)
   we use chunk pagination (chunk=1, chunk=2, ...).

3. **idMal as universal key** — Entries where ``idMal`` is null are
   AniList-exclusive titles with no MAL equivalent.  We skip them and
   count the skips so the caller can report them.

4. **Tags → Themes** — AniList tags (rank ≥ 60, top 10 by rank) fill the
   ``themes`` field that the MAL API never returns.  This improves
   preference-analysis quality for AniList imports.

5. **averageScore normalisation** — AniList's ``averageScore`` is 0–100.
   We divide by 10 to match the MAL 0–10 float stored in ``mal_score``.

6. **Score rounding** — AniList's ``POINT_10_DECIMAL`` format returns
   floats (e.g. 7.5).  We round to the nearest int to match our
   ``user_score: int`` column.  0 = unscored in both systems.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.core.logging import logger

# ── API constants ────────────────────────────────────────

ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
ANILIST_PER_CHUNK = 500          # entries per chunk request
ANILIST_CHUNK_DELAY = 0.7        # seconds between chunk requests (90 req/min limit)
ANILIST_TAG_MIN_RANK = 60        # minimum tag relevance rank to include as theme
ANILIST_TAG_MAX = 10             # max number of tags to use as themes

# ── GraphQL query ────────────────────────────────────────

ANILIST_LIST_QUERY = """
query ($username: String, $chunk: Int, $perChunk: Int) {
  MediaListCollection(userName: $username, type: ANIME, chunk: $chunk, perChunk: $perChunk) {
    hasNextChunk
    lists {
      entries {
        score(format: POINT_10_DECIMAL)
        status
        progress
        media {
          idMal
          title { romaji english }
          format
          status
          episodes
          genres
          description(asHtml: false)
          averageScore
          popularity
          season
          seasonYear
          studios(isMain: true) { nodes { name } }
          tags { name rank }
          coverImage { large }
        }
      }
    }
  }
}
"""

# ── Status / format maps ─────────────────────────────────

_WATCH_STATUS_MAP: dict[str, str] = {
    "COMPLETED": "completed",
    "CURRENT": "watching",
    "PLANNING": "plan_to_watch",
    "DROPPED": "dropped",
    "PAUSED": "on_hold",
    "REPEATING": "watching",
}

_FORMAT_MAP: dict[str, str] = {
    "TV": "TV",
    "TV_SHORT": "TV",
    "MOVIE": "Movie",
    "SPECIAL": "Special",
    "OVA": "OVA",
    "ONA": "ONA",
    "MUSIC": "Music",
}

_AIRING_STATUS_MAP: dict[str, str] = {
    "FINISHED": "Finished Airing",
    "RELEASING": "Currently Airing",
    "NOT_YET_RELEASED": "Not yet aired",
    "CANCELLED": "Finished Airing",
    "HIATUS": "Currently Airing",
}


# ── Public interface ─────────────────────────────────────


async def fetch_user_animelist_anilist(
    username: str,
) -> tuple[list[dict], int]:
    """Fetch a user's complete anime list from the AniList GraphQL API.

    Returns a tuple of:
    - ``entries``: list of raw AniList entry dicts (all chunks combined)
    - ``skipped_count``: number of entries skipped because ``idMal`` was null

    Handles chunk pagination automatically for large lists.

    Raises ``ValueError`` if the AniList user is not found.
    Raises ``httpx.HTTPStatusError`` on unexpected HTTP errors.
    """
    all_entries: list[dict] = []
    chunk = 1

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            logger.info(
                "Fetching AniList animelist for %s — chunk %d", username, chunk
            )

            payload = {
                "query": ANILIST_LIST_QUERY,
                "variables": {
                    "username": username,
                    "chunk": chunk,
                    "perChunk": ANILIST_PER_CHUNK,
                },
            }

            resp = await client.post(
                ANILIST_GRAPHQL_URL,
                json=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )

            if resp.status_code == 429:
                logger.warning("AniList rate limit hit, backing off 5s…")
                await asyncio.sleep(5.0)
                continue

            resp.raise_for_status()
            body = resp.json()

            # GraphQL errors land in body["errors"] with HTTP 200
            errors = body.get("errors")
            if errors:
                for err in errors:
                    if err.get("status") == 404 or "Not Found" in err.get("message", ""):
                        raise ValueError(
                            f"AniList user '{username}' not found or list is private."
                        )
                raise ValueError(
                    f"AniList GraphQL error: {errors[0].get('message', 'unknown')}"
                )

            collection = (
                body.get("data", {})
                .get("MediaListCollection") or {}
            )

            if collection is None:
                # AniList returns null MediaListCollection for non-existent users
                raise ValueError(
                    f"AniList user '{username}' not found or list is private."
                )

            # Flatten all lists → entries
            lists = collection.get("lists") or []
            for lst in lists:
                all_entries.extend(lst.get("entries") or [])

            has_next = collection.get("hasNextChunk", False)
            logger.info(
                "AniList chunk %d: +%d entries (total so far: %d, hasNext: %s)",
                chunk,
                sum(len(lst.get("entries") or []) for lst in lists),
                len(all_entries),
                has_next,
            )

            if not has_next:
                break

            chunk += 1
            await asyncio.sleep(ANILIST_CHUNK_DELAY)

    logger.info(
        "Finished fetching AniList animelist for %s — %d raw entries",
        username,
        len(all_entries),
    )

    # Parse and count skips
    parsed: list[dict] = []
    skipped = 0
    for raw in all_entries:
        result = parse_anilist_entry(raw)
        if result is None:
            skipped += 1
        else:
            parsed.append(result)

    logger.info(
        "AniList parse complete for %s: %d entries, %d skipped (no idMal)",
        username,
        len(parsed),
        skipped,
    )
    return parsed, skipped


def parse_anilist_entry(raw: dict) -> dict | None:
    """Parse a raw AniList animelist entry into our normalised format.

    The AniList GraphQL response entry looks like::

        {
            "score": 8.5,
            "status": "COMPLETED",
            "progress": 26,
            "media": {
                "idMal": 1,
                "title": { "romaji": "Cowboy Bebop", "english": "Cowboy Bebop" },
                "format": "TV",
                "status": "FINISHED",
                "episodes": 26,
                "genres": ["Action", "Sci-Fi"],
                "description": "In the year 2071...",
                "averageScore": 87,
                "popularity": 500000,
                "season": "SPRING",
                "seasonYear": 1998,
                "studios": { "nodes": [{"name": "Sunrise"}] },
                "tags": [{"name": "Space", "rank": 90}, ...],
                "coverImage": { "large": "https://..." }
            }
        }

    Returns ``None`` if ``media.idMal`` is null (AniList-exclusive title).
    """
    media = raw.get("media") or {}
    mal_id = media.get("idMal")

    if not mal_id:
        return None

    # ── User relationship ─────────────────────────────
    raw_score = raw.get("score") or 0
    user_score = round(raw_score) if raw_score else 0  # 0 = unscored
    watch_status = _WATCH_STATUS_MAP.get(
        raw.get("status", ""), raw.get("status", "unknown")
    )
    episodes_watched = raw.get("progress") or 0

    # ── Titles ────────────────────────────────────────
    titles = media.get("title") or {}
    title = titles.get("romaji") or titles.get("english") or "Unknown"
    title_english = titles.get("english")

    # ── Image ─────────────────────────────────────────
    cover = media.get("coverImage") or {}
    image_url = cover.get("large")

    # ── Type + airing status ──────────────────────────
    anime_type = _FORMAT_MAP.get(media.get("format", ""), media.get("format"))
    anime_status = _AIRING_STATUS_MAP.get(
        media.get("status", ""), media.get("status")
    )

    # ── Episodes ──────────────────────────────────────
    total_episodes = media.get("episodes")

    # ── Genres (array → comma-separated) ──────────────
    genres_list = media.get("genres") or []
    genres = ", ".join(genres_list) if genres_list else None

    # ── Tags → Themes (rank ≥ 60, top 10 by rank) ────
    tags = media.get("tags") or []
    relevant_tags = sorted(
        [t for t in tags if (t.get("rank") or 0) >= ANILIST_TAG_MIN_RANK],
        key=lambda t: t.get("rank", 0),
        reverse=True,
    )[:ANILIST_TAG_MAX]
    themes = ", ".join(t["name"] for t in relevant_tags if "name" in t) or None

    # ── Synopsis ──────────────────────────────────────
    synopsis = media.get("description")

    # ── Community score (AniList 0–100 → 0–10 float) ─
    avg = media.get("averageScore")
    mal_score = round(avg / 10.0, 2) if avg else None

    # ── Popularity ────────────────────────────────────
    mal_members = media.get("popularity")

    # ── Season / year ─────────────────────────────────
    raw_season = media.get("season")
    season = raw_season.lower() if raw_season else None
    year = media.get("seasonYear")

    # ── Studios (main only) ───────────────────────────
    studios_nodes = (media.get("studios") or {}).get("nodes") or []
    studios = ", ".join(n["name"] for n in studios_nodes if "name" in n) or None

    return {
        "mal_anime_id": mal_id,
        "title": title,
        "title_english": title_english,
        "image_url": image_url,
        "watch_status": watch_status,
        "user_score": user_score,
        "episodes_watched": episodes_watched,
        "total_episodes": total_episodes,
        "anime_type": anime_type,
        "anime_status": anime_status,
        "synopsis": synopsis,
        "genres": genres,
        "themes": themes,
        "studios": studios,
        "season": season,
        "year": year,
        "mal_score": mal_score,
        "mal_members": mal_members,
    }
