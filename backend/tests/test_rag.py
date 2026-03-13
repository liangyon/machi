"""Tests for the RAG retriever service.

These tests cover the pure functions in rag.py:
• build_search_queries — generates search queries from preference profiles
• rerank_by_preferences — computes preference scores for candidates
• _compute_preference_score — the core scoring function
• Helper functions for query building

All tests use mock data — no vector store, no OpenAI, no network.
They test the "intelligence" layer that sits between the vector store
and the recommendation engine.

Why test these?
───────────────
Query generation determines WHAT we search for.  If queries are bad,
we get irrelevant candidates.  Preference scoring determines HOW we
rank results.  If scoring is wrong, good recommendations get buried.
These are the highest-leverage tests for recommendation quality.
"""

import pytest

from app.services.rag import (
    build_search_queries,
    rerank_by_preferences,
    _build_genre_query,
    _build_top_shows_query,
    _build_theme_query,
    _get_genre_affinity_map,
    _get_theme_affinity_map,
    _compute_preference_score,
)


# ═════════════════════════════════════════════════════════
# Mock preference profiles
# ═════════════════════════════════════════════════════════

# A rich profile (typical user with 100+ anime watched)
MOCK_RICH_PROFILE = {
    "total_watched": 150,
    "total_scored": 120,
    "mean_score": 7.5,
    "genre_affinity": [
        {"genre": "Action", "count": 45, "avg_score": 7.8, "affinity": 0.85},
        {"genre": "Sci-Fi", "count": 20, "avg_score": 8.2, "affinity": 0.78},
        {"genre": "Drama", "count": 30, "avg_score": 7.5, "affinity": 0.72},
        {"genre": "Comedy", "count": 25, "avg_score": 6.5, "affinity": 0.55},
        {"genre": "Romance", "count": 10, "avg_score": 6.0, "affinity": 0.40},
    ],
    "theme_affinity": [
        {"genre": "Time Travel", "count": 5, "avg_score": 9.0, "affinity": 0.90},
        {"genre": "Psychological", "count": 8, "avg_score": 8.5, "affinity": 0.82},
        {"genre": "Military", "count": 6, "avg_score": 7.0, "affinity": 0.60},
    ],
    "studio_affinity": [
        {"genre": "MAPPA", "count": 10, "avg_score": 8.0, "affinity": 0.80},
    ],
    "preferred_formats": {"TV": 100, "Movie": 30, "OVA": 10, "ONA": 10},
    "completion_rate": 0.85,
    "top_10": [
        {"title": "Steins;Gate", "user_score": 10, "mal_anime_id": 9253},
        {"title": "Death Note", "user_score": 10, "mal_anime_id": 1535},
        {"title": "Monster", "user_score": 10, "mal_anime_id": 19},
        {"title": "Cowboy Bebop", "user_score": 9, "mal_anime_id": 1},
    ],
    "watch_era_preference": {
        "2020s": 50,
        "2010s": 60,
        "2000s": 25,
        "1990s": 15,
    },
}

# An empty profile (new user, no data)
MOCK_EMPTY_PROFILE = {
    "total_watched": 0,
    "total_scored": 0,
    "mean_score": 0.0,
    "genre_affinity": [],
    "theme_affinity": [],
    "studio_affinity": [],
    "preferred_formats": {},
    "completion_rate": 0.0,
    "top_10": [],
    "watch_era_preference": {},
}

# A minimal profile (user with very few anime)
MOCK_MINIMAL_PROFILE = {
    "total_watched": 3,
    "total_scored": 2,
    "mean_score": 8.0,
    "genre_affinity": [
        {"genre": "Action", "count": 2, "avg_score": 8.0, "affinity": 0.70},
    ],
    "theme_affinity": [],
    "studio_affinity": [],
    "preferred_formats": {"TV": 3},
    "completion_rate": 1.0,
    "top_10": [
        {"title": "Attack on Titan", "user_score": 9, "mal_anime_id": 16498},
    ],
    "watch_era_preference": {"2010s": 3},
}


# ═════════════════════════════════════════════════════════
# Tests: build_search_queries
# ═════════════════════════════════════════════════════════


class TestBuildSearchQueries:
    """Test search query generation from preference profiles."""

    def test_rich_profile_generates_multiple_queries(self):
        """A rich profile should generate 3 queries (genre, shows, themes)."""
        queries = build_search_queries(MOCK_RICH_PROFILE)

        assert len(queries) == 3
        # All queries should be non-empty strings
        for q in queries:
            assert isinstance(q, str)
            assert len(q) > 10

    def test_empty_profile_generates_fallback(self):
        """An empty profile should generate a fallback query."""
        queries = build_search_queries(MOCK_EMPTY_PROFILE)

        assert len(queries) == 1
        assert "popular" in queries[0].lower() or "rated" in queries[0].lower()

    def test_minimal_profile_generates_some_queries(self):
        """A minimal profile should generate at least 1-2 queries."""
        queries = build_search_queries(MOCK_MINIMAL_PROFILE)

        assert len(queries) >= 1
        # Should have at least a genre query
        assert any("Action" in q for q in queries)

    def test_queries_contain_user_preferences(self):
        """Queries should reflect the user's actual preferences."""
        queries = build_search_queries(MOCK_RICH_PROFILE)

        all_text = " ".join(queries)
        # Top genres should appear
        assert "Action" in all_text
        assert "Sci-Fi" in all_text
        # Top shows should appear
        assert "Steins;Gate" in all_text
        # Top themes should appear
        assert "Time Travel" in all_text


# ═════════════════════════════════════════════════════════
# Tests: Individual query builders
# ═════════════════════════════════════════════════════════


class TestBuildGenreQuery:
    """Test genre-based query construction."""

    def test_top_3_genres(self):
        """Should use top 3 genres by affinity."""
        query = _build_genre_query(MOCK_RICH_PROFILE)
        assert query is not None
        assert "Action" in query
        assert "Sci-Fi" in query
        assert "Drama" in query
        # 4th genre (Comedy) should NOT be included
        assert "Comedy" not in query

    def test_empty_genres(self):
        """No genres should return None."""
        assert _build_genre_query(MOCK_EMPTY_PROFILE) is None


class TestBuildTopShowsQuery:
    """Test top-shows-based query construction."""

    def test_top_3_shows(self):
        """Should reference top 3 shows by score."""
        query = _build_top_shows_query(MOCK_RICH_PROFILE)
        assert query is not None
        assert "Steins;Gate" in query
        assert "Death Note" in query
        assert "Monster" in query

    def test_empty_top_10(self):
        """No top shows should return None."""
        assert _build_top_shows_query(MOCK_EMPTY_PROFILE) is None

    def test_single_show(self):
        """Profile with only 1 top show should still work."""
        query = _build_top_shows_query(MOCK_MINIMAL_PROFILE)
        assert query is not None
        assert "Attack on Titan" in query


class TestBuildThemeQuery:
    """Test theme-based query construction."""

    def test_top_3_themes(self):
        """Should use top 3 themes by affinity."""
        query = _build_theme_query(MOCK_RICH_PROFILE)
        assert query is not None
        assert "Time Travel" in query
        assert "Psychological" in query
        assert "Military" in query

    def test_empty_themes(self):
        """No themes should return None."""
        assert _build_theme_query(MOCK_EMPTY_PROFILE) is None


# ═════════════════════════════════════════════════════════
# Tests: Preference scoring
# ═════════════════════════════════════════════════════════


class TestComputePreferenceScore:
    """Test the preference scoring function.

    This function computes how well an anime matches a user's
    preferences on a 0–1 scale.  It considers:
    - Genre match (40% weight)
    - Theme match (20% weight)
    - Format match (20% weight)
    - Era match (20% weight)
    """

    def setup_method(self):
        """Set up common test data."""
        self.genre_affinities = _get_genre_affinity_map(MOCK_RICH_PROFILE)
        self.theme_affinities = _get_theme_affinity_map(MOCK_RICH_PROFILE)
        self.preferred_formats = MOCK_RICH_PROFILE["preferred_formats"]
        self.era_prefs = MOCK_RICH_PROFILE["watch_era_preference"]

    def test_perfect_match(self):
        """Anime matching top genres, themes, format, and era should score high."""
        metadata = {
            "genres": "Action, Sci-Fi",
            "themes": "Time Travel, Psychological",
            "anime_type": "TV",
            "year": 2015,  # 2010s decade
        }

        score = _compute_preference_score(
            metadata=metadata,
            genre_affinities=self.genre_affinities,
            theme_affinities=self.theme_affinities,
            preferred_formats=self.preferred_formats,
            era_prefs=self.era_prefs,
        )

        # Should be high (close to 1.0)
        assert score > 0.6

    def test_poor_match(self):
        """Anime with genres the user doesn't like should score low."""
        metadata = {
            "genres": "Romance",  # Low affinity (0.40)
            "themes": "",
            "anime_type": "OVA",  # Rarely watched format
            "year": 1985,  # 1980s — not in their era prefs
        }

        score = _compute_preference_score(
            metadata=metadata,
            genre_affinities=self.genre_affinities,
            theme_affinities=self.theme_affinities,
            preferred_formats=self.preferred_formats,
            era_prefs=self.era_prefs,
        )

        # Should be lower than perfect match
        assert score < 0.5

    def test_no_metadata_returns_neutral(self):
        """Anime with no metadata should get a neutral score (~0.5)."""
        score = _compute_preference_score(
            metadata={},
            genre_affinities=self.genre_affinities,
            theme_affinities=self.theme_affinities,
            preferred_formats=self.preferred_formats,
            era_prefs=self.era_prefs,
        )

        # Should be around 0.5 (neutral)
        assert 0.4 <= score <= 0.6

    def test_score_between_0_and_1(self):
        """Score should always be between 0 and 1."""
        test_cases = [
            {"genres": "Action", "year": 2020, "anime_type": "TV"},
            {"genres": "Romance, Comedy", "year": 1990},
            {},
            {"genres": "Unknown Genre"},
        ]

        for metadata in test_cases:
            score = _compute_preference_score(
                metadata=metadata,
                genre_affinities=self.genre_affinities,
                theme_affinities=self.theme_affinities,
                preferred_formats=self.preferred_formats,
                era_prefs=self.era_prefs,
            )
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for {metadata}"

    def test_empty_preferences_returns_neutral(self):
        """If user has no preferences, everything should score neutral."""
        score = _compute_preference_score(
            metadata={"genres": "Action", "year": 2020, "anime_type": "TV"},
            genre_affinities={},
            theme_affinities={},
            preferred_formats={},
            era_prefs={},
        )

        assert 0.4 <= score <= 0.6


# ═════════════════════════════════════════════════════════
# Tests: rerank_by_preferences
# ═════════════════════════════════════════════════════════


class TestRerankByPreferences:
    """Test the full re-ranking pipeline."""

    def test_adds_scores_to_candidates(self):
        """Re-ranking should add preference_score and combined_score."""
        candidates = [
            {
                "mal_id": 1,
                "title": "Test Anime",
                "similarity_score": 0.8,
                "metadata": {"genres": "Action", "year": 2020, "anime_type": "TV"},
            },
        ]

        result = rerank_by_preferences(candidates, MOCK_RICH_PROFILE)

        assert len(result) == 1
        assert "preference_score" in result[0]
        assert "combined_score" in result[0]
        assert 0.0 <= result[0]["preference_score"] <= 1.0
        assert 0.0 <= result[0]["combined_score"] <= 1.0

    def test_combined_score_formula(self):
        """Combined score should be 0.6 × similarity + 0.4 × preference."""
        candidates = [
            {
                "mal_id": 1,
                "title": "Test",
                "similarity_score": 0.5,
                "metadata": {},
            },
        ]

        result = rerank_by_preferences(candidates, MOCK_EMPTY_PROFILE)

        sim = result[0]["similarity_score"]
        pref = result[0]["preference_score"]
        expected = round(0.6 * sim + 0.4 * pref, 4)
        assert result[0]["combined_score"] == expected

    def test_high_affinity_anime_ranked_higher(self):
        """Anime matching user's top genres should rank higher after re-ranking."""
        candidates = [
            {
                "mal_id": 1,
                "title": "Action Anime",
                "similarity_score": 0.7,  # same similarity
                "metadata": {"genres": "Action, Sci-Fi", "anime_type": "TV", "year": 2020},
            },
            {
                "mal_id": 2,
                "title": "Romance Anime",
                "similarity_score": 0.7,  # same similarity
                "metadata": {"genres": "Romance", "anime_type": "OVA", "year": 1985},
            },
        ]

        result = rerank_by_preferences(candidates, MOCK_RICH_PROFILE)

        # Action anime should have higher combined score
        action = next(c for c in result if c["mal_id"] == 1)
        romance = next(c for c in result if c["mal_id"] == 2)
        assert action["combined_score"] > romance["combined_score"]

    def test_empty_candidates(self):
        """Empty candidate list should return empty list."""
        result = rerank_by_preferences([], MOCK_RICH_PROFILE)
        assert result == []


# ═════════════════════════════════════════════════════════
# Tests: Affinity map helpers
# ═════════════════════════════════════════════════════════


class TestAffinityMaps:
    """Test the affinity map conversion helpers."""

    def test_genre_affinity_map(self):
        """Should convert list to {genre: affinity} dict."""
        result = _get_genre_affinity_map(MOCK_RICH_PROFILE)
        assert result["Action"] == 0.85
        assert result["Sci-Fi"] == 0.78
        assert result["Romance"] == 0.40

    def test_theme_affinity_map(self):
        """Should convert list to {theme: affinity} dict."""
        result = _get_theme_affinity_map(MOCK_RICH_PROFILE)
        assert result["Time Travel"] == 0.90
        assert result["Psychological"] == 0.82

    def test_empty_profile_maps(self):
        """Empty profile should produce empty maps."""
        assert _get_genre_affinity_map(MOCK_EMPTY_PROFILE) == {}
        assert _get_theme_affinity_map(MOCK_EMPTY_PROFILE) == {}
