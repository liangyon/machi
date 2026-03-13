"""Anime catalog ingestion — bulk-fetches anime metadata for the knowledge base.

This service populates the ``AnimeCatalogEntry`` table with anime from
multiple Jikan API sources (top anime, seasonal, by genre).  Each anime
gets a rich ``embedding_text`` built from its metadata, ready to be
embedded into the vector store.

Why Jikan (not the official MAL API)?
─────────────────────────────────────
• Jikan has discovery endpoints: ``/top/anime``, ``/seasons/{year}/{season}``,
  ``/anime?genres={id}`` — perfect for bulk catalog building.
• No authentication needed (MAL API requires a Client ID).
• Jikan includes **themes** and **demographics** that the MAL API v2
  doesn't provide.  These are valuable signals for recommendations.
• We already have Jikan parsing code from Phase 1.

Design decisions
────────────────
1. **Upsert by mal_id** — The same anime may appear in "top anime",
   "seasonal", and "genre: action".  We upsert (insert or update) by
   ``mal_id`` to avoid duplicates while keeping the richest metadata.

2. **Rate limiting** — Jikan allows ~3 requests/second for free.
   We sleep 0.4s between requests and back off on 429 responses.

3. **Source tracking** — Each entry records its ingestion source
   (e.g. "top_anime_page_3", "seasonal_2024_winter") for debugging
   and understanding catalog coverage.

4. **Embedding text** — Built immediately on ingest.  This is the
   rich text document that gets embedded into the vector store.
   Storing it in the DB means we can re-embed without re-fetching.

5. **Pure functions for parsing/text-building** — Easy to unit test
   without any network or DB dependencies.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx

from app.core.logging import logger

# ── Jikan API constants ──────────────────────────────────

JIKAN_BASE = "https://api.jikan.moe/v4"
JIKAN_RATE_LIMIT_DELAY = 0.4  # ~3 req/s
JIKAN_BACKOFF_DELAY = 2.0     # on 429 rate limit
JIKAN_PAGE_SIZE = 25           # Jikan returns 25 items per page


# ═════════════════════════════════════════════════════════
# Fetching — async functions that hit the Jikan API
# ═════════════════════════════════════════════════════════


async def fetch_top_anime(
    pages: int = 10,
    on_page: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Fetch top-ranked anime from Jikan.

    Jikan's ``/top/anime`` returns anime sorted by MAL score,
    25 per page.  10 pages = 250 anime.

    Args:
        pages: Number of pages to fetch (25 anime per page).
        on_page: Optional callback(page_num, total_so_far) for progress.

    Returns:
        List of raw Jikan anime data dicts.
    """
    all_anime: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(1, pages + 1):
            url = f"{JIKAN_BASE}/top/anime"
            params = {"page": page, "sfw": "false"}

            data = await _jikan_get(client, url, params)
            if data is None:
                break

            anime_list = data.get("data", [])
            if not anime_list:
                break

            all_anime.extend(anime_list)

            if on_page:
                on_page(page, len(all_anime))

            logger.info(
                "Top anime page %d: got %d (total: %d)",
                page, len(anime_list), len(all_anime),
            )

            await asyncio.sleep(JIKAN_RATE_LIMIT_DELAY)

    return all_anime


async def fetch_seasonal_anime(
    year: int,
    season: str,
    pages: int = 4,
) -> list[dict]:
    """Fetch anime from a specific season.

    Jikan's ``/seasons/{year}/{season}`` returns anime that aired
    in that season.  Useful for getting recent and popular titles.

    Args:
        year: e.g. 2024
        season: "winter" | "spring" | "summer" | "fall"
        pages: Number of pages to fetch.

    Returns:
        List of raw Jikan anime data dicts.
    """
    all_anime: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(1, pages + 1):
            url = f"{JIKAN_BASE}/seasons/{year}/{season}"
            params = {"page": page, "sfw": "false"}

            data = await _jikan_get(client, url, params)
            if data is None:
                break

            anime_list = data.get("data", [])
            if not anime_list:
                break

            all_anime.extend(anime_list)

            logger.info(
                "Seasonal %s %d page %d: got %d (total: %d)",
                season, year, page, len(anime_list), len(all_anime),
            )

            await asyncio.sleep(JIKAN_RATE_LIMIT_DELAY)

    return all_anime


async def fetch_anime_by_genre(
    genre_id: int,
    genre_name: str,
    pages: int = 4,
) -> list[dict]:
    """Fetch anime filtered by genre.

    Jikan's ``/anime?genres={id}`` returns anime matching a genre,
    sorted by score.  Useful for filling gaps in underrepresented
    genres.

    Common genre IDs (from MAL):
        1=Action, 2=Adventure, 4=Comedy, 8=Drama, 10=Fantasy,
        14=Horror, 22=Romance, 24=Sci-Fi, 36=Slice of Life,
        37=Supernatural, 7=Mystery, 41=Suspense

    Args:
        genre_id: MAL genre ID.
        genre_name: Human-readable name (for logging/source tracking).
        pages: Number of pages to fetch.

    Returns:
        List of raw Jikan anime data dicts.
    """
    all_anime: list[dict] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for page in range(1, pages + 1):
            url = f"{JIKAN_BASE}/anime"
            params = {
                "genres": str(genre_id),
                "order_by": "score",
                "sort": "desc",
                "page": page,
                "sfw": "false",
            }

            data = await _jikan_get(client, url, params)
            if data is None:
                break

            anime_list = data.get("data", [])
            if not anime_list:
                break

            all_anime.extend(anime_list)

            logger.info(
                "Genre %s (id=%d) page %d: got %d (total: %d)",
                genre_name, genre_id, page, len(anime_list), len(all_anime),
            )

            await asyncio.sleep(JIKAN_RATE_LIMIT_DELAY)

    return all_anime


# ═════════════════════════════════════════════════════════
# Parsing — pure functions, no network, easy to test
# ═════════════════════════════════════════════════════════


def parse_jikan_to_catalog(raw: dict, source: str = "") -> dict:
    """Parse a raw Jikan anime response into our catalog format.

    This is a pure function — no DB, no API calls.  It maps Jikan's
    nested JSON structure into a flat dict matching the
    ``AnimeCatalogEntry`` model fields.

    Args:
        raw: A single anime dict from any Jikan endpoint.
        source: Where this came from (e.g. "top_anime_page_1").

    Returns:
        Dict with keys matching AnimeCatalogEntry columns.
        Returns None-valued fields gracefully for missing data.
    """
    # Extract image URL (Jikan nests images deeply)
    images = raw.get("images", {})
    jpg = images.get("jpg", {})
    image_url = jpg.get("large_image_url") or jpg.get("image_url")

    # Extract comma-separated names from Jikan's list-of-dicts format
    genres = _extract_names(raw.get("genres", []))
    themes = _extract_names(raw.get("themes", []))
    demographics = _extract_names(raw.get("demographics", []))
    studios = _extract_names(raw.get("studios", []))

    # Extract related anime MAL IDs
    relations = raw.get("relations", [])
    related_ids = _extract_related_anime_ids(relations)

    # Extract English title from titles list
    title_english = None
    for t in raw.get("titles", []):
        if t.get("type") == "English":
            title_english = t.get("title")
            break
    # Fallback to top-level title_english if titles list didn't have it
    if not title_english:
        title_english = raw.get("title_english")

    parsed = {
        "mal_id": raw.get("mal_id"),
        "title": raw.get("title", "Unknown"),
        "title_english": title_english,
        "image_url": image_url,
        "anime_type": raw.get("type"),
        "anime_status": raw.get("status"),
        "total_episodes": raw.get("episodes"),
        "synopsis": raw.get("synopsis"),
        "genres": genres,
        "themes": themes,
        "demographics": demographics,
        "studios": studios,
        "season": raw.get("season"),
        "year": raw.get("year"),
        "mal_score": raw.get("score"),
        "mal_members": raw.get("members"),
        "mal_rank": raw.get("rank"),
        "mal_popularity": raw.get("popularity"),
        "related_anime_ids": related_ids,
        "source": source,
    }

    # Build the embedding text immediately
    parsed["embedding_text"] = build_embedding_text(parsed)

    return parsed


# ═════════════════════════════════════════════════════════
# Embedding text construction — the most important design
# decision in RAG.  What you embed determines what the LLM
# can find.
# ═════════════════════════════════════════════════════════


def build_embedding_text(anime: dict) -> str:
    """Build a rich text document for vector embedding.

    This is the text that gets turned into a vector and stored in
    ChromaDB.  When a user asks for recommendations, their query
    gets embedded and compared against these vectors via cosine
    similarity.

    The format is structured but natural language — LLMs understand
    both.  We include every signal that could help match:

    - **Title** — exact match for "something like Cowboy Bebop"
    - **Genres/Themes** — "action sci-fi space" matches genre queries
    - **Synopsis** — semantic meaning ("dark", "psychological", etc.)
    - **Studio** — fans of Madhouse or Bones have studio preferences
    - **Score/Popularity** — quality signal for filtering
    - **Year/Type** — era and format preferences

    Example output::

        Title: Cowboy Bebop
        English Title: Cowboy Bebop
        Type: TV | 26 episodes | 1998
        Genres: Action, Sci-Fi
        Themes: Space, Adult Cast
        Studios: Sunrise
        Score: 8.75 (1,500,000 members)
        Synopsis: In the year 2071, humanity has colonized...

    Args:
        anime: Dict with catalog fields (from parse_jikan_to_catalog).

    Returns:
        A multi-line string ready for embedding.
    """
    lines: list[str] = []

    # Title (always present)
    lines.append(f"Title: {anime.get('title', 'Unknown')}")

    # English title (if different from main title)
    title_en = anime.get("title_english")
    if title_en and title_en != anime.get("title"):
        lines.append(f"English Title: {title_en}")

    # Type, episodes, year — combined into one line for density
    type_parts: list[str] = []
    if anime.get("anime_type"):
        type_parts.append(anime["anime_type"])
    if anime.get("total_episodes"):
        type_parts.append(f"{anime['total_episodes']} episodes")
    if anime.get("year"):
        type_parts.append(str(anime["year"]))
    if type_parts:
        lines.append(f"Type: {' | '.join(type_parts)}")

    # Genres
    if anime.get("genres"):
        lines.append(f"Genres: {anime['genres']}")

    # Themes (Jikan-specific, very valuable for recommendations)
    if anime.get("themes"):
        lines.append(f"Themes: {anime['themes']}")

    # Demographics
    if anime.get("demographics"):
        lines.append(f"Demographics: {anime['demographics']}")

    # Studios
    if anime.get("studios"):
        lines.append(f"Studios: {anime['studios']}")

    # Score and popularity
    if anime.get("mal_score"):
        score_str = f"Score: {anime['mal_score']}"
        if anime.get("mal_members"):
            score_str += f" ({anime['mal_members']:,} members)"
        lines.append(score_str)

    # Synopsis (the richest semantic signal)
    if anime.get("synopsis"):
        # Clean up common Jikan synopsis artifacts
        synopsis = anime["synopsis"].strip()
        # Remove "[Written by MAL Rewrite]" suffix
        synopsis = synopsis.replace("[Written by MAL Rewrite]", "").strip()
        if synopsis:
            lines.append(f"Synopsis: {synopsis}")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════
# Database operations — upsert parsed anime into the catalog
# ═════════════════════════════════════════════════════════


def upsert_catalog_entries(
    db,  # SQLAlchemy Session
    parsed_entries: list[dict],
) -> dict:
    """Upsert parsed anime entries into the AnimeCatalogEntry table.

    "Upsert" means: if an anime with this ``mal_id`` already exists,
    update its fields.  If it doesn't exist, insert a new row.
    This is how we handle the same anime appearing from multiple
    sources without creating duplicates.

    Args:
        db: SQLAlchemy session.
        parsed_entries: List of dicts from ``parse_jikan_to_catalog()``.

    Returns:
        Dict with counts: {"inserted": N, "updated": M, "skipped": K}
    """
    from sqlalchemy import select
    from app.models.anime import AnimeCatalogEntry

    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    for entry_data in parsed_entries:
        mal_id = entry_data.get("mal_id")
        if not mal_id:
            stats["skipped"] += 1
            continue

        # Check if this anime already exists in the catalog
        existing = db.execute(
            select(AnimeCatalogEntry).where(AnimeCatalogEntry.mal_id == mal_id)
        ).scalar_one_or_none()

        if existing:
            # Update existing entry with potentially richer data
            _update_catalog_entry(existing, entry_data)
            stats["updated"] += 1
        else:
            # Insert new entry
            # Remove 'embedding_text' temporarily to set it via the model
            new_entry = AnimeCatalogEntry(
                mal_id=entry_data["mal_id"],
                title=entry_data["title"],
                title_english=entry_data.get("title_english"),
                image_url=entry_data.get("image_url"),
                anime_type=entry_data.get("anime_type"),
                anime_status=entry_data.get("anime_status"),
                total_episodes=entry_data.get("total_episodes"),
                synopsis=entry_data.get("synopsis"),
                genres=entry_data.get("genres"),
                themes=entry_data.get("themes"),
                demographics=entry_data.get("demographics"),
                studios=entry_data.get("studios"),
                season=entry_data.get("season"),
                year=entry_data.get("year"),
                mal_score=entry_data.get("mal_score"),
                mal_members=entry_data.get("mal_members"),
                mal_rank=entry_data.get("mal_rank"),
                mal_popularity=entry_data.get("mal_popularity"),
                related_anime_ids=entry_data.get("related_anime_ids"),
                embedding_text=entry_data.get("embedding_text"),
                source=entry_data.get("source"),
                is_embedded=False,
            )
            db.add(new_entry)
            stats["inserted"] += 1

    db.commit()
    return stats


def _update_catalog_entry(existing, new_data: dict) -> None:
    """Update an existing catalog entry with new data.

    We only overwrite fields if the new data is non-None and
    potentially richer (e.g. has themes where the old one didn't).
    We always regenerate the embedding text since the data may
    have changed.
    """
    # Fields to update (only if new value is not None)
    update_fields = [
        "title", "title_english", "image_url", "anime_type",
        "anime_status", "total_episodes", "synopsis", "genres",
        "themes", "demographics", "studios", "season", "year",
        "mal_score", "mal_members", "mal_rank", "mal_popularity",
        "related_anime_ids",
    ]

    changed = False
    for field in update_fields:
        new_val = new_data.get(field)
        if new_val is not None:
            old_val = getattr(existing, field, None)
            if new_val != old_val:
                setattr(existing, field, new_val)
                changed = True

    # Always regenerate embedding text if anything changed
    if changed:
        existing.embedding_text = new_data.get("embedding_text") or build_embedding_text(
            {field: getattr(existing, field) for field in update_fields}
        )
        # Mark as needing re-embedding since the text changed
        existing.is_embedded = False


# ═════════════════════════════════════════════════════════
# Private helpers
# ═════════════════════════════════════════════════════════


async def _jikan_get(
    client: httpx.AsyncClient,
    url: str,
    params: dict,
    max_retries: int = 3,
) -> dict | None:
    """Make a GET request to Jikan with retry and rate-limit handling.

    Returns the parsed JSON response, or None if all retries fail.
    """
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, params=params)

            if resp.status_code == 429:
                # Rate limited — back off and retry
                wait = JIKAN_BACKOFF_DELAY * (attempt + 1)
                logger.warning(
                    "Jikan rate limited (429), backing off %.1fs (attempt %d/%d)",
                    wait, attempt + 1, max_retries,
                )
                await asyncio.sleep(wait)
                continue

            if resp.status_code == 404:
                logger.warning("Jikan 404 for %s", url)
                return None

            resp.raise_for_status()
            return resp.json()

        except httpx.TimeoutException:
            logger.warning(
                "Jikan timeout for %s (attempt %d/%d)",
                url, attempt + 1, max_retries,
            )
            await asyncio.sleep(JIKAN_BACKOFF_DELAY)

        except Exception as exc:
            logger.warning(
                "Jikan request failed for %s: %s (attempt %d/%d)",
                url, exc, attempt + 1, max_retries,
            )
            await asyncio.sleep(JIKAN_BACKOFF_DELAY)

    logger.error("All retries exhausted for %s", url)
    return None


def _extract_names(items: list[dict]) -> str | None:
    """Extract comma-separated names from Jikan's list-of-dicts format.

    Jikan returns genres/themes/studios as:
        [{"mal_id": 1, "name": "Action"}, {"mal_id": 24, "name": "Sci-Fi"}]

    We flatten to: "Action, Sci-Fi"
    """
    if not items:
        return None
    names = [item["name"] for item in items if "name" in item]
    return ", ".join(names) if names else None


def _extract_related_anime_ids(relations: list[dict]) -> str | None:
    """Extract related anime MAL IDs from Jikan's relations structure.

    Jikan returns relations as::

        [
            {
                "relation": "Sequel",
                "entry": [{"mal_id": 5, "type": "anime", "name": "..."}]
            },
            ...
        ]

    We extract all anime MAL IDs as a comma-separated string.
    """
    if not relations:
        return None

    ids: list[int] = []
    for rel in relations:
        for entry in rel.get("entry", []):
            if entry.get("type") == "anime" and entry.get("mal_id"):
                ids.append(entry["mal_id"])

    return ", ".join(str(i) for i in ids) if ids else None
