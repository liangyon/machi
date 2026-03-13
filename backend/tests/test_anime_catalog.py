"""Tests for the anime catalog ingestion service.

These tests cover the pure functions in anime_catalog.py:
• Jikan response parsing (parse_jikan_to_catalog)
• Embedding text construction (build_embedding_text)
• Helper functions (_extract_names, _extract_related_anime_ids)

All tests use mock data — no network calls, no DB, no API keys.
They run in milliseconds and test the core data transformation logic.

Why test these specifically?
────────────────────────────
The parsing and embedding text functions are the foundation of our
knowledge base.  If parsing is wrong, we store bad data.  If the
embedding text is wrong, the vector store can't find relevant anime.
These are the highest-value tests we can write.
"""

import pytest

from app.services.anime_catalog import (
    parse_jikan_to_catalog,
    build_embedding_text,
    _extract_names,
    _extract_related_anime_ids,
)


# ═════════════════════════════════════════════════════════
# Mock Jikan response data
# ═════════════════════════════════════════════════════════

# A realistic Jikan /anime response for Cowboy Bebop
MOCK_JIKAN_COWBOY_BEBOP = {
    "mal_id": 1,
    "title": "Cowboy Bebop",
    "title_english": "Cowboy Bebop",
    "titles": [
        {"type": "Default", "title": "Cowboy Bebop"},
        {"type": "English", "title": "Cowboy Bebop"},
        {"type": "Japanese", "title": "カウボーイビバップ"},
    ],
    "type": "TV",
    "episodes": 26,
    "status": "Finished Airing",
    "score": 8.75,
    "rank": 28,
    "popularity": 43,
    "members": 1800000,
    "season": "spring",
    "year": 1998,
    "synopsis": "Crime is timeless. By the year 2071, humanity has expanded across the galaxy. [Written by MAL Rewrite]",
    "images": {
        "jpg": {
            "image_url": "https://cdn.myanimelist.net/images/anime/4/19644.jpg",
            "large_image_url": "https://cdn.myanimelist.net/images/anime/4/19644l.jpg",
        }
    },
    "genres": [
        {"mal_id": 1, "name": "Action"},
        {"mal_id": 24, "name": "Sci-Fi"},
    ],
    "themes": [
        {"mal_id": 29, "name": "Space"},
        {"mal_id": 50, "name": "Adult Cast"},
    ],
    "demographics": [
        {"mal_id": 42, "name": "Seinen"},
    ],
    "studios": [
        {"mal_id": 14, "name": "Sunrise"},
    ],
    "relations": [
        {
            "relation": "Adaptation",
            "entry": [
                {"mal_id": 173, "type": "manga", "name": "Cowboy Bebop"},
            ],
        },
        {
            "relation": "Side Story",
            "entry": [
                {"mal_id": 5, "type": "anime", "name": "Cowboy Bebop: Tengoku no Tobira"},
                {"mal_id": 17205, "type": "anime", "name": "Cowboy Bebop: Ein no Natsuyasumi"},
            ],
        },
    ],
}

# A minimal Jikan response (many fields missing)
MOCK_JIKAN_MINIMAL = {
    "mal_id": 99999,
    "title": "Some Obscure OVA",
    "type": "OVA",
    "episodes": 1,
    "status": "Finished Airing",
    "images": {},
    "genres": [],
    "themes": [],
    "demographics": [],
    "studios": [],
}


# ═════════════════════════════════════════════════════════
# Tests: parse_jikan_to_catalog
# ═════════════════════════════════════════════════════════


class TestParseJikanToCatalog:
    """Test the Jikan response → catalog format parser."""

    def test_full_entry(self):
        """Parse a complete Jikan response with all fields present."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP, source="top_anime_page_1")

        assert parsed["mal_id"] == 1
        assert parsed["title"] == "Cowboy Bebop"
        assert parsed["title_english"] == "Cowboy Bebop"
        assert parsed["anime_type"] == "TV"
        assert parsed["total_episodes"] == 26
        assert parsed["anime_status"] == "Finished Airing"
        assert parsed["mal_score"] == 8.75
        assert parsed["mal_rank"] == 28
        assert parsed["mal_popularity"] == 43
        assert parsed["mal_members"] == 1800000
        assert parsed["season"] == "spring"
        assert parsed["year"] == 1998
        assert parsed["source"] == "top_anime_page_1"

    def test_genres_extracted(self):
        """Genres should be comma-separated string."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        assert parsed["genres"] == "Action, Sci-Fi"

    def test_themes_extracted(self):
        """Themes should be comma-separated string."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        assert parsed["themes"] == "Space, Adult Cast"

    def test_demographics_extracted(self):
        """Demographics should be comma-separated string."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        assert parsed["demographics"] == "Seinen"

    def test_studios_extracted(self):
        """Studios should be comma-separated string."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        assert parsed["studios"] == "Sunrise"

    def test_image_url_prefers_large(self):
        """Should prefer large_image_url over image_url."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        assert parsed["image_url"] == "https://cdn.myanimelist.net/images/anime/4/19644l.jpg"

    def test_related_anime_ids(self):
        """Should extract only anime (not manga) related IDs."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        # Should have IDs 5 and 17205 (anime), but NOT 173 (manga)
        assert parsed["related_anime_ids"] == "5, 17205"

    def test_english_title_from_titles_list(self):
        """Should extract English title from the titles list."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        assert parsed["title_english"] == "Cowboy Bebop"

    def test_english_title_fallback(self):
        """Should fall back to title_english field if titles list doesn't have it."""
        raw = {
            "mal_id": 100,
            "title": "テスト",
            "title_english": "Test Anime",
            "titles": [{"type": "Default", "title": "テスト"}],
            "images": {},
            "genres": [],
            "themes": [],
            "demographics": [],
            "studios": [],
        }
        parsed = parse_jikan_to_catalog(raw)
        assert parsed["title_english"] == "Test Anime"

    def test_minimal_entry(self):
        """Parse an entry with many fields missing — should not crash."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_MINIMAL)

        assert parsed["mal_id"] == 99999
        assert parsed["title"] == "Some Obscure OVA"
        assert parsed["genres"] is None
        assert parsed["themes"] is None
        assert parsed["demographics"] is None
        assert parsed["studios"] is None
        assert parsed["synopsis"] is None
        assert parsed["year"] is None
        assert parsed["image_url"] is None
        assert parsed["related_anime_ids"] is None

    def test_embedding_text_generated(self):
        """Parsing should automatically generate embedding_text."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        assert parsed["embedding_text"] is not None
        assert "Cowboy Bebop" in parsed["embedding_text"]
        assert "Action" in parsed["embedding_text"]

    def test_synopsis_cleaned(self):
        """The [Written by MAL Rewrite] suffix should be removed from embedding text."""
        parsed = parse_jikan_to_catalog(MOCK_JIKAN_COWBOY_BEBOP)
        assert "[Written by MAL Rewrite]" not in parsed["embedding_text"]
        assert "Crime is timeless" in parsed["embedding_text"]


# ═════════════════════════════════════════════════════════
# Tests: build_embedding_text
# ═════════════════════════════════════════════════════════


class TestBuildEmbeddingText:
    """Test the embedding text constructor.

    This is the most important function for RAG quality.
    The text it produces is what gets embedded into vectors.
    """

    def test_full_anime(self):
        """Full anime should produce a rich, multi-line document."""
        anime = {
            "title": "Steins;Gate",
            "title_english": "Steins;Gate",
            "anime_type": "TV",
            "total_episodes": 24,
            "year": 2011,
            "genres": "Sci-Fi, Suspense",
            "themes": "Time Travel",
            "demographics": "Seinen",
            "studios": "White Fox",
            "mal_score": 9.07,
            "mal_members": 2500000,
            "synopsis": "Eccentric scientist Rintarou Okabe discovers time travel.",
        }

        text = build_embedding_text(anime)

        assert "Title: Steins;Gate" in text
        assert "Type: TV | 24 episodes | 2011" in text
        assert "Genres: Sci-Fi, Suspense" in text
        assert "Themes: Time Travel" in text
        assert "Demographics: Seinen" in text
        assert "Studios: White Fox" in text
        assert "Score: 9.07 (2,500,000 members)" in text
        assert "Synopsis: Eccentric scientist" in text

    def test_english_title_different_from_main(self):
        """English title should appear only if different from main title."""
        anime = {
            "title": "Shingeki no Kyojin",
            "title_english": "Attack on Titan",
        }
        text = build_embedding_text(anime)
        assert "Title: Shingeki no Kyojin" in text
        assert "English Title: Attack on Titan" in text

    def test_english_title_same_as_main(self):
        """English title should NOT appear if same as main title."""
        anime = {
            "title": "Cowboy Bebop",
            "title_english": "Cowboy Bebop",
        }
        text = build_embedding_text(anime)
        assert "Title: Cowboy Bebop" in text
        assert "English Title:" not in text

    def test_minimal_anime(self):
        """Anime with only a title should still produce valid text."""
        anime = {"title": "Unknown OVA"}
        text = build_embedding_text(anime)
        assert text == "Title: Unknown OVA"

    def test_missing_title_defaults(self):
        """Missing title should default to 'Unknown'."""
        text = build_embedding_text({})
        assert text == "Title: Unknown"

    def test_synopsis_mal_rewrite_removed(self):
        """[Written by MAL Rewrite] should be stripped from synopsis."""
        anime = {
            "title": "Test",
            "synopsis": "A great anime. [Written by MAL Rewrite]",
        }
        text = build_embedding_text(anime)
        assert "[Written by MAL Rewrite]" not in text
        assert "Synopsis: A great anime." in text

    def test_score_without_members(self):
        """Score should display without member count if members is missing."""
        anime = {
            "title": "Test",
            "mal_score": 7.5,
        }
        text = build_embedding_text(anime)
        assert "Score: 7.5" in text
        assert "members" not in text

    def test_type_line_partial(self):
        """Type line should handle partial data (e.g. only year)."""
        anime = {"title": "Test", "year": 2020}
        text = build_embedding_text(anime)
        assert "Type: 2020" in text

    def test_type_line_episodes_only(self):
        """Type line with only episodes."""
        anime = {"title": "Test", "total_episodes": 12}
        text = build_embedding_text(anime)
        assert "Type: 12 episodes" in text


# ═════════════════════════════════════════════════════════
# Tests: Helper functions
# ═════════════════════════════════════════════════════════


class TestExtractNames:
    """Test the _extract_names helper."""

    def test_normal_list(self):
        items = [{"mal_id": 1, "name": "Action"}, {"mal_id": 24, "name": "Sci-Fi"}]
        assert _extract_names(items) == "Action, Sci-Fi"

    def test_empty_list(self):
        assert _extract_names([]) is None

    def test_single_item(self):
        items = [{"mal_id": 1, "name": "Action"}]
        assert _extract_names(items) == "Action"

    def test_missing_name_key(self):
        """Items without 'name' key should be skipped."""
        items = [{"mal_id": 1, "name": "Action"}, {"mal_id": 2}]
        assert _extract_names(items) == "Action"

    def test_all_missing_name(self):
        """If all items lack 'name', return None."""
        items = [{"mal_id": 1}, {"mal_id": 2}]
        assert _extract_names(items) is None


class TestExtractRelatedAnimeIds:
    """Test the _extract_related_anime_ids helper."""

    def test_mixed_relations(self):
        """Should extract only anime IDs, not manga."""
        relations = [
            {
                "relation": "Adaptation",
                "entry": [{"mal_id": 173, "type": "manga", "name": "CB Manga"}],
            },
            {
                "relation": "Sequel",
                "entry": [
                    {"mal_id": 5, "type": "anime", "name": "CB Movie"},
                    {"mal_id": 17205, "type": "anime", "name": "CB Special"},
                ],
            },
        ]
        result = _extract_related_anime_ids(relations)
        assert result == "5, 17205"

    def test_empty_relations(self):
        assert _extract_related_anime_ids([]) is None
        assert _extract_related_anime_ids(None) is None

    def test_no_anime_relations(self):
        """Relations with only manga should return None."""
        relations = [
            {
                "relation": "Adaptation",
                "entry": [{"mal_id": 1, "type": "manga", "name": "Test"}],
            },
        ]
        assert _extract_related_anime_ids(relations) is None

    def test_single_anime_relation(self):
        relations = [
            {
                "relation": "Sequel",
                "entry": [{"mal_id": 42, "type": "anime", "name": "Sequel"}],
            },
        ]
        assert _extract_related_anime_ids(relations) == "42"
