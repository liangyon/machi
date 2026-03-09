"""Tests for the MAL ingestion service.

Split into two categories:

1. **Parsing tests** (no network) — verify our field mapping against
   mock MAL API v2 / Jikan response structures.  These are fast and
   reliable.

2. **Live API tests** (hit real MAL API) — smoke tests that verify
   our HTTP client works against the real API.  These require
   ``MAL_CLIENT_ID`` to be set and can fail if the API is down.
   Marked with ``@pytest.mark.asyncio``.

Run parsing tests only (fast, no network):
    uv run --extra dev pytest tests/test_mal_service.py -v -k "parse"

Run all including live API tests:
    uv run --extra dev pytest tests/test_mal_service.py -v -s
"""

import pytest

from app.services.mal import (
    fetch_user_animelist,
    fetch_anime_details_jikan,
    parse_mal_animelist_entry,
    parse_jikan_anime_details,
)
from app.core.config import settings


# ── pytest-asyncio detection ─────────────────────────────

try:
    import pytest_asyncio  # noqa: F401
    HAS_ASYNCIO = True
except ImportError:
    HAS_ASYNCIO = False


# ── Parsing tests (no network, always run) ───────────────


def test_parse_mal_animelist_entry():
    """Test parsing a raw MAL API v2 animelist entry.

    This uses a mock response structure matching what the official
    MAL API v2 returns.  No network needed.
    """
    raw = {
        "node": {
            "id": 1,
            "title": "Cowboy Bebop",
            "main_picture": {
                "medium": "https://example.com/medium.jpg",
                "large": "https://example.com/large.jpg",
            },
            "num_episodes": 26,
            "status": "finished_airing",
            "media_type": "tv",
            "genres": [
                {"id": 1, "name": "Action"},
                {"id": 24, "name": "Sci-Fi"},
            ],
            "synopsis": "A space bounty hunter crew...",
            "studios": [
                {"id": 14, "name": "Sunrise"},
            ],
            "start_season": {"year": 1998, "season": "spring"},
            "mean": 8.75,
            "num_list_users": 1500000,
            "alternative_titles": {"en": "Cowboy Bebop"},
        },
        "list_status": {
            "status": "completed",
            "score": 9,
            "num_episodes_watched": 26,
            "updated_at": "2023-01-01T00:00:00+00:00",
        },
    }

    parsed = parse_mal_animelist_entry(raw)

    assert parsed["mal_anime_id"] == 1
    assert parsed["title"] == "Cowboy Bebop"
    assert parsed["title_english"] == "Cowboy Bebop"
    assert parsed["image_url"] == "https://example.com/large.jpg"
    assert parsed["watch_status"] == "completed"
    assert parsed["user_score"] == 9
    assert parsed["episodes_watched"] == 26
    assert parsed["total_episodes"] == 26
    assert parsed["anime_type"] == "TV"
    assert parsed["anime_status"] == "Finished Airing"
    assert parsed["synopsis"] == "A space bounty hunter crew..."
    assert parsed["genres"] == "Action, Sci-Fi"
    assert parsed["studios"] == "Sunrise"
    assert parsed["year"] == 1998
    assert parsed["season"] == "spring"
    assert parsed["mal_score"] == 8.75
    assert parsed["mal_members"] == 1500000


def test_parse_mal_entry_minimal():
    """Test parsing a MAL entry with minimal data (some fields missing).

    Real MAL data often has missing fields — no genres, no synopsis,
    no season.  Our parser should handle this gracefully.
    """
    raw = {
        "node": {
            "id": 99999,
            "title": "Some Obscure OVA",
            "num_episodes": 1,
            "media_type": "ova",
        },
        "list_status": {
            "status": "plan_to_watch",
            "score": 0,
            "num_episodes_watched": 0,
        },
    }

    parsed = parse_mal_animelist_entry(raw)

    assert parsed["mal_anime_id"] == 99999
    assert parsed["title"] == "Some Obscure OVA"
    assert parsed["watch_status"] == "plan_to_watch"
    assert parsed["user_score"] == 0
    assert parsed["genres"] is None
    assert parsed["synopsis"] is None
    assert parsed["studios"] is None
    assert parsed["year"] is None
    assert parsed["image_url"] is None
    assert parsed["anime_type"] == "OVA"


def test_parse_mal_entry_all_statuses():
    """Verify all MAL watch statuses map correctly."""
    statuses = {
        "watching": "watching",
        "completed": "completed",
        "on_hold": "on_hold",
        "dropped": "dropped",
        "plan_to_watch": "plan_to_watch",
    }

    for mal_status, expected in statuses.items():
        raw = {
            "node": {"id": 1, "title": "Test"},
            "list_status": {"status": mal_status, "score": 0},
        }
        parsed = parse_mal_animelist_entry(raw)
        assert parsed["watch_status"] == expected, (
            f"MAL status '{mal_status}' should map to '{expected}', "
            f"got '{parsed['watch_status']}'"
        )


def test_parse_jikan_anime_details():
    """Test parsing a Jikan anime detail response (fallback parser)."""
    detail = {
        "synopsis": "A space bounty hunter crew...",
        "genres": [
            {"mal_id": 1, "name": "Action"},
            {"mal_id": 24, "name": "Sci-Fi"},
        ],
        "themes": [
            {"mal_id": 29, "name": "Space"},
        ],
        "studios": [
            {"mal_id": 14, "name": "Sunrise"},
        ],
        "season": "spring",
        "year": 1998,
        "score": 8.75,
        "members": 1500000,
        "episodes": 26,
        "type": "TV",
        "status": "Finished Airing",
    }

    parsed = parse_jikan_anime_details(detail)

    assert parsed["synopsis"] == "A space bounty hunter crew..."
    assert parsed["genres"] == "Action, Sci-Fi"
    assert parsed["themes"] == "Space"
    assert parsed["studios"] == "Sunrise"
    assert parsed["year"] == 1998
    assert parsed["mal_score"] == 8.75


# ── Live API tests (require network + MAL_CLIENT_ID) ─────


needs_mal_api = pytest.mark.skipif(
    not HAS_ASYNCIO or not settings.MAL_CLIENT_ID,
    reason="Requires pytest-asyncio and MAL_CLIENT_ID in .env",
)


@needs_mal_api
@pytest.mark.asyncio
async def test_fetch_animelist_real_user():
    """Fetch a real MAL user's animelist via the official API.

    Uses '@me' pattern won't work without user OAuth, so we use
    a known public MAL username.  If this fails, the user may have
    made their list private.
    """
    # Use a well-known MAL user — adjust if needed
    entries = await fetch_user_animelist("Xinil")

    assert len(entries) > 0, "Expected at least 1 entry"

    # Check MAL API v2 structure
    first = entries[0]
    assert "node" in first, f"Expected 'node' key, got: {list(first.keys())}"
    assert "id" in first["node"], "Expected 'id' in node"
    assert "title" in first["node"], "Expected 'title' in node"

    # Parse it and verify
    parsed = parse_mal_animelist_entry(first)
    assert parsed["mal_anime_id"] is not None
    assert parsed["title"] != "Unknown"

    print(f"✓ Fetched {len(entries)} entries, first: {parsed['title']}")


@needs_mal_api
@pytest.mark.asyncio
async def test_fetch_animelist_invalid_user():
    """Fetching a non-existent user should raise ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await fetch_user_animelist("this_user_definitely_does_not_exist_12345xyz")


@pytest.mark.skipif(not HAS_ASYNCIO, reason="Requires pytest-asyncio")
@pytest.mark.asyncio
async def test_fetch_jikan_anime_details_cowboy_bebop():
    """Fetch Cowboy Bebop details from Jikan (fallback API)."""
    detail = await fetch_anime_details_jikan(1)

    assert detail is not None, "Failed to fetch Cowboy Bebop from Jikan"
    assert detail.get("title") == "Cowboy Bebop"

    parsed = parse_jikan_anime_details(detail)
    assert "Action" in (parsed["genres"] or "")
    assert parsed["themes"] is not None  # Jikan has themes, MAL API doesn't

    print(f"✓ Jikan Cowboy Bebop: genres={parsed['genres']}, themes={parsed['themes']}")
