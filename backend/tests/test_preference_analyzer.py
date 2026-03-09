"""Unit tests for the preference analyzer.

The preference analyzer is a pure function — no DB, no API calls.
We can test it by creating mock AnimeEntry objects and verifying
the computed profile matches our expectations.

This is the best place to start testing because:
1. Zero infrastructure needed (no server, no DB, no API keys)
2. Fast — runs in milliseconds
3. Tests the core "intelligence" of our system
4. Easy to add edge cases (empty list, all unscored, single entry, etc.)
"""

import pytest
from unittest.mock import MagicMock

from app.services.preference_analyzer import analyze_preferences


def _make_entry(**kwargs) -> MagicMock:
    """Create a mock AnimeEntry with sensible defaults.

    Why MagicMock instead of real ORM objects?
    ──────────────────────────────────────────
    Real AnimeEntry objects need a DB session and table to exist.
    MagicMock lets us create objects with any attributes we want,
    which is perfect for unit testing a pure function that just
    reads attributes off the objects it receives.
    """
    defaults = {
        "mal_anime_id": 1,
        "title": "Test Anime",
        "title_english": None,
        "image_url": None,
        "watch_status": "completed",
        "user_score": 8,
        "episodes_watched": 12,
        "total_episodes": 12,
        "anime_type": "TV",
        "anime_status": "Finished Airing",
        "synopsis": "A test anime.",
        "genres": "Action, Adventure",
        "themes": "Isekai",
        "studios": "MAPPA",
        "season": "winter",
        "year": 2023,
        "mal_score": 8.5,
        "mal_members": 100000,
    }
    defaults.update(kwargs)

    entry = MagicMock()
    for key, value in defaults.items():
        setattr(entry, key, value)
    return entry


class TestAnalyzePreferences:
    """Test suite for the analyze_preferences function."""

    def test_empty_list_returns_empty_profile(self):
        """An empty list should return a valid but zeroed-out profile."""
        profile = analyze_preferences([])

        assert profile["total_watched"] == 0
        assert profile["total_scored"] == 0
        assert profile["mean_score"] == 0.0
        assert profile["genre_affinity"] == []
        assert profile["top_10"] == []
        assert profile["completion_rate"] == 0.0

    def test_single_entry(self):
        """A single completed, scored entry should produce a valid profile."""
        entry = _make_entry(
            mal_anime_id=1,
            title="Cowboy Bebop",
            user_score=10,
            watch_status="completed",
            genres="Action, Sci-Fi",
            themes="Space",
            studios="Sunrise",
            year=1998,
        )

        profile = analyze_preferences([entry])

        assert profile["total_watched"] == 1
        assert profile["total_scored"] == 1
        assert profile["mean_score"] == 10.0
        assert profile["completion_rate"] == 1.0
        assert len(profile["top_10"]) == 1
        assert profile["top_10"][0]["title"] == "Cowboy Bebop"

        # Genre affinity should have Action and Sci-Fi
        genre_names = [g["genre"] for g in profile["genre_affinity"]]
        assert "Action" in genre_names
        assert "Sci-Fi" in genre_names

    def test_unscored_entries_excluded_from_mean(self):
        """Entries with score 0 (unscored) should not affect the mean score.

        This is important because MAL uses 0 to mean 'not scored',
        not 'terrible'.  Including them would drag down averages.
        """
        scored = _make_entry(user_score=8, watch_status="completed")
        unscored = _make_entry(user_score=0, watch_status="completed", mal_anime_id=2)

        profile = analyze_preferences([scored, unscored])

        assert profile["total_scored"] == 1
        assert profile["mean_score"] == 8.0

    def test_plan_to_watch_not_counted_as_watched(self):
        """Plan-to-watch entries shouldn't count toward total_watched."""
        watched = _make_entry(watch_status="completed", mal_anime_id=1)
        planned = _make_entry(watch_status="plan_to_watch", mal_anime_id=2, user_score=0)

        profile = analyze_preferences([watched, planned])

        assert profile["total_watched"] == 1

    def test_completion_rate(self):
        """Completion rate = completed / started (excluding plan_to_watch)."""
        completed = _make_entry(watch_status="completed", mal_anime_id=1)
        dropped = _make_entry(watch_status="dropped", mal_anime_id=2)
        watching = _make_entry(watch_status="watching", mal_anime_id=3)
        planned = _make_entry(watch_status="plan_to_watch", mal_anime_id=4, user_score=0)

        profile = analyze_preferences([completed, dropped, watching, planned])

        # 1 completed out of 3 started (planned doesn't count)
        assert profile["completion_rate"] == pytest.approx(1 / 3, rel=0.01)

    def test_genre_affinity_weights_score_over_count(self):
        """Genre affinity should weight score higher than count.

        Our formula: affinity = 0.4 × norm_count + 0.6 × norm_score

        So a genre with fewer entries but higher scores should rank
        higher than one with many entries but low scores.
        """
        # 3 action anime scored 5/10
        action_entries = [
            _make_entry(mal_anime_id=i, genres="Action", user_score=5)
            for i in range(1, 4)
        ]
        # 1 drama anime scored 10/10
        drama_entry = _make_entry(mal_anime_id=10, genres="Drama", user_score=10)

        profile = analyze_preferences(action_entries + [drama_entry])

        genre_map = {g["genre"]: g for g in profile["genre_affinity"]}

        # Drama should have higher affinity despite fewer entries
        assert genre_map["Drama"]["affinity"] > genre_map["Action"]["affinity"]

    def test_top_10_sorted_by_score(self):
        """Top 10 should be sorted by user_score descending."""
        entries = [
            _make_entry(mal_anime_id=i, title=f"Anime {i}", user_score=i)
            for i in range(1, 15)
        ]

        profile = analyze_preferences(entries)

        assert len(profile["top_10"]) == 10
        scores = [e["user_score"] for e in profile["top_10"]]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == 14  # highest score

    def test_era_preference(self):
        """Era preference should group anime by decade."""
        entries = [
            _make_entry(mal_anime_id=1, year=1998),
            _make_entry(mal_anime_id=2, year=2005),
            _make_entry(mal_anime_id=3, year=2015),
            _make_entry(mal_anime_id=4, year=2023),
            _make_entry(mal_anime_id=5, year=2021),
        ]

        profile = analyze_preferences(entries)

        assert profile["watch_era_preference"]["1990s"] == 1
        assert profile["watch_era_preference"]["2000s"] == 1
        assert profile["watch_era_preference"]["2010s"] == 1
        assert profile["watch_era_preference"]["2020s"] == 2

    def test_score_distribution(self):
        """Score distribution should count entries per score value."""
        entries = [
            _make_entry(mal_anime_id=1, user_score=8),
            _make_entry(mal_anime_id=2, user_score=8),
            _make_entry(mal_anime_id=3, user_score=9),
            _make_entry(mal_anime_id=4, user_score=7),
        ]

        profile = analyze_preferences(entries)

        assert profile["score_distribution"]["8"] == 2
        assert profile["score_distribution"]["9"] == 1
        assert profile["score_distribution"]["7"] == 1

    def test_format_preference(self):
        """Format preference should count anime by type (TV, Movie, etc.)."""
        entries = [
            _make_entry(mal_anime_id=1, anime_type="TV"),
            _make_entry(mal_anime_id=2, anime_type="TV"),
            _make_entry(mal_anime_id=3, anime_type="Movie"),
        ]

        profile = analyze_preferences(entries)

        assert profile["preferred_formats"]["TV"] == 2
        assert profile["preferred_formats"]["Movie"] == 1
