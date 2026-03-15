"""Tests for Phase 3.5 — Feedback-driven preference tuning.

Testing strategy
────────────────
The ``apply_feedback_adjustments()`` function is pure — no DB, no API.
We can test it by creating mock feedback objects and verifying the
adjusted profile matches our expectations.

These tests verify:
1. Liked feedback boosts genre/theme affinities
2. Disliked feedback reduces genre/theme affinities
3. Watched feedback has no effect on affinities
4. Adjustments are capped at [0.0, 1.0]
5. New genres from feedback are added to the profile
6. Empty feedback returns the profile unchanged
7. Multiple feedbacks accumulate correctly
8. The original profile is not mutated (pure function)

Why test this so thoroughly?
────────────────────────────
This is the "learning" mechanism of the recommendation engine.
If it's wrong, the system either:
- Doesn't learn at all (feedback ignored)
- Learns too aggressively (filter bubble)
- Learns the wrong thing (boosts when it should penalise)

Each test case represents a real scenario we want to handle correctly.
"""

import copy
from unittest.mock import MagicMock

import pytest

from app.services.preference_analyzer import (
    apply_feedback_adjustments,
    _apply_deltas,
    LIKED_BOOST,
    DISLIKED_PENALTY,
    MIN_AFFINITY,
    MAX_AFFINITY,
)


# ═════════════════════════════════════════════════════════
# Test fixtures
# ═════════════════════════════════════════════════════════

# A realistic base profile (same shape as what analyze_preferences produces)
BASE_PROFILE = {
    "total_watched": 100,
    "mean_score": 7.5,
    "genre_affinity": [
        {"genre": "Action", "count": 30, "avg_score": 7.8, "affinity": 0.70},
        {"genre": "Romance", "count": 15, "avg_score": 6.5, "affinity": 0.45},
        {"genre": "Sci-Fi", "count": 20, "avg_score": 8.0, "affinity": 0.75},
        {"genre": "Comedy", "count": 10, "avg_score": 6.0, "affinity": 0.35},
    ],
    "theme_affinity": [
        {"genre": "Psychological", "count": 8, "avg_score": 8.5, "affinity": 0.80},
        {"genre": "Isekai", "count": 12, "avg_score": 6.0, "affinity": 0.40},
    ],
    "top_10": [],
    "preferred_formats": {"TV": 80, "Movie": 20},
    "watch_era_preference": {"2020s": 50, "2010s": 30},
}


def _make_feedback(feedback_type: str, genres: str = "", themes: str = "") -> MagicMock:
    """Create a mock RecommendationFeedback object.

    Why MagicMock?
    ──────────────
    Same reason as in test_preference_analyzer.py — we don't need
    a real ORM object for a pure function test.  MagicMock lets us
    set any attributes we want.
    """
    fb = MagicMock()
    fb.feedback_type = feedback_type
    fb.genres = genres
    fb.themes = themes
    return fb


# ═════════════════════════════════════════════════════════
# Tests: apply_feedback_adjustments
# ═════════════════════════════════════════════════════════


class TestApplyFeedbackAdjustments:
    """Test the main feedback adjustment function."""

    def test_no_feedback_returns_profile_unchanged(self):
        """With no feedback, the profile should be returned as-is."""
        result = apply_feedback_adjustments(BASE_PROFILE, [])
        assert result == BASE_PROFILE

    def test_does_not_mutate_original_profile(self):
        """The original profile dict should not be modified.

        This is critical — if we mutate the original, the base
        profile in the database would be corrupted.  The function
        must return a NEW dict.
        """
        original = copy.deepcopy(BASE_PROFILE)
        feedbacks = [_make_feedback("liked", genres="Action, Thriller")]

        apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        # Original should be unchanged
        assert BASE_PROFILE == original

    def test_liked_boosts_genre_affinity(self):
        """Liking an anime should boost its genres' affinity."""
        feedbacks = [_make_feedback("liked", genres="Action, Sci-Fi")]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        # Action was 0.70, should now be 0.70 + 0.05 = 0.75
        assert genre_map["Action"] == pytest.approx(0.70 + LIKED_BOOST, abs=0.001)
        # Sci-Fi was 0.75, should now be 0.75 + 0.05 = 0.80
        assert genre_map["Sci-Fi"] == pytest.approx(0.75 + LIKED_BOOST, abs=0.001)
        # Romance should be unchanged
        assert genre_map["Romance"] == pytest.approx(0.45, abs=0.001)

    def test_disliked_reduces_genre_affinity(self):
        """Disliking an anime should reduce its genres' affinity."""
        feedbacks = [_make_feedback("disliked", genres="Romance, Comedy")]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        # Romance was 0.45, should now be 0.45 - 0.03 = 0.42
        assert genre_map["Romance"] == pytest.approx(0.45 - DISLIKED_PENALTY, abs=0.001)
        # Comedy was 0.35, should now be 0.35 - 0.03 = 0.32
        assert genre_map["Comedy"] == pytest.approx(0.35 - DISLIKED_PENALTY, abs=0.001)
        # Action should be unchanged
        assert genre_map["Action"] == pytest.approx(0.70, abs=0.001)

    def test_watched_does_not_affect_affinity(self):
        """'Watched' feedback should not change any affinities.

        'Watched' only affects the exclusion set (handled in the API
        layer), not the preference profile.
        """
        feedbacks = [_make_feedback("watched", genres="Action, Romance")]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        assert genre_map["Action"] == pytest.approx(0.70, abs=0.001)
        assert genre_map["Romance"] == pytest.approx(0.45, abs=0.001)

    def test_liked_boosts_theme_affinity(self):
        """Liking should also boost theme affinities."""
        feedbacks = [_make_feedback("liked", themes="Psychological")]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        theme_map = {t["genre"]: t["affinity"] for t in result["theme_affinity"]}

        # Psychological was 0.80, should now be 0.85
        assert theme_map["Psychological"] == pytest.approx(0.80 + LIKED_BOOST, abs=0.001)
        # Isekai should be unchanged
        assert theme_map["Isekai"] == pytest.approx(0.40, abs=0.001)

    def test_multiple_likes_accumulate(self):
        """Multiple likes for the same genre should accumulate.

        If the user likes 3 action anime, Action gets +0.15 total.
        """
        feedbacks = [
            _make_feedback("liked", genres="Action"),
            _make_feedback("liked", genres="Action"),
            _make_feedback("liked", genres="Action"),
        ]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        expected = 0.70 + (LIKED_BOOST * 3)
        assert genre_map["Action"] == pytest.approx(expected, abs=0.001)

    def test_mixed_feedback_nets_correctly(self):
        """Likes and dislikes for the same genre should net out.

        2 likes (+0.10) and 1 dislike (-0.03) = net +0.07
        """
        feedbacks = [
            _make_feedback("liked", genres="Action"),
            _make_feedback("liked", genres="Action"),
            _make_feedback("disliked", genres="Action"),
        ]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        expected = 0.70 + (LIKED_BOOST * 2) - DISLIKED_PENALTY
        assert genre_map["Action"] == pytest.approx(expected, abs=0.001)

    def test_affinity_capped_at_max(self):
        """Affinity should never exceed MAX_AFFINITY (1.0).

        Even with many likes, we cap at 1.0 to prevent any single
        genre from dominating the re-ranking formula.
        """
        # Sci-Fi is at 0.75.  6 likes would push it to 1.05, but
        # it should be capped at 1.0.
        feedbacks = [
            _make_feedback("liked", genres="Sci-Fi")
            for _ in range(6)
        ]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        assert genre_map["Sci-Fi"] == MAX_AFFINITY

    def test_affinity_capped_at_min(self):
        """Affinity should never go below MIN_AFFINITY (0.0).

        Even with many dislikes, we floor at 0.0.
        """
        # Comedy is at 0.35.  15 dislikes would push it to -0.10,
        # but it should be floored at 0.0.
        feedbacks = [
            _make_feedback("disliked", genres="Comedy")
            for _ in range(15)
        ]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        assert genre_map["Comedy"] == MIN_AFFINITY

    def test_new_genre_added_from_feedback(self):
        """Liking an anime with a genre not in the profile should add it.

        If the user likes a "Horror" anime but has never watched Horror,
        we add Horror to the profile with a base affinity of 0.3 + boost.
        """
        feedbacks = [_make_feedback("liked", genres="Horror")]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        assert "Horror" in genre_map
        assert genre_map["Horror"] == pytest.approx(0.3 + LIKED_BOOST, abs=0.001)

    def test_new_theme_added_from_feedback(self):
        """Liking an anime with a new theme should add it to the profile."""
        feedbacks = [_make_feedback("liked", themes="Time Travel")]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        theme_map = {t["genre"]: t["affinity"] for t in result["theme_affinity"]}

        assert "Time Travel" in theme_map
        assert theme_map["Time Travel"] == pytest.approx(0.3 + LIKED_BOOST, abs=0.001)

    def test_result_sorted_by_affinity_descending(self):
        """After adjustments, genres should be re-sorted by affinity."""
        feedbacks = [
            # Boost Comedy a lot so it rises in the ranking
            _make_feedback("liked", genres="Comedy"),
            _make_feedback("liked", genres="Comedy"),
            _make_feedback("liked", genres="Comedy"),
            _make_feedback("liked", genres="Comedy"),
            _make_feedback("liked", genres="Comedy"),
        ]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        affinities = [g["affinity"] for g in result["genre_affinity"]]
        assert affinities == sorted(affinities, reverse=True)

    def test_handles_none_genres_gracefully(self):
        """Feedback with None genres should not crash."""
        fb = MagicMock()
        fb.feedback_type = "liked"
        fb.genres = None
        fb.themes = None

        # Should not raise
        result = apply_feedback_adjustments(BASE_PROFILE, [fb])
        assert result is not None

    def test_handles_empty_string_genres(self):
        """Feedback with empty string genres should not crash."""
        feedbacks = [_make_feedback("liked", genres="", themes="")]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        # Profile should be unchanged (no genres to adjust)
        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}
        assert genre_map["Action"] == pytest.approx(0.70, abs=0.001)

    def test_handles_dict_feedback_objects(self):
        """Should also work with plain dicts (not just ORM objects).

        The function uses hasattr() to check if it's an ORM object
        or a dict, so it should handle both.  This is useful for
        testing without the ORM.
        """
        feedbacks = [
            {"feedback_type": "liked", "genres": "Action", "themes": ""},
            {"feedback_type": "disliked", "genres": "Romance", "themes": ""},
        ]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        genre_map = {g["genre"]: g["affinity"] for g in result["genre_affinity"]}

        assert genre_map["Action"] == pytest.approx(0.70 + LIKED_BOOST, abs=0.001)
        assert genre_map["Romance"] == pytest.approx(0.45 - DISLIKED_PENALTY, abs=0.001)

    def test_non_affinity_fields_preserved(self):
        """Fields other than genre/theme affinity should be unchanged.

        We only modify genre_affinity and theme_affinity.  Everything
        else (total_watched, mean_score, top_10, etc.) should pass
        through untouched.
        """
        feedbacks = [_make_feedback("liked", genres="Action")]

        result = apply_feedback_adjustments(BASE_PROFILE, feedbacks)

        assert result["total_watched"] == 100
        assert result["mean_score"] == 7.5
        assert result["preferred_formats"] == {"TV": 80, "Movie": 20}
        assert result["watch_era_preference"] == {"2020s": 50, "2010s": 30}


# ═════════════════════════════════════════════════════════
# Tests: _apply_deltas (internal helper)
# ═════════════════════════════════════════════════════════


class TestApplyDeltas:
    """Test the delta application helper directly."""

    def test_no_deltas_returns_unchanged(self):
        """Empty deltas should return the list unchanged."""
        affinity_list = [
            {"genre": "Action", "count": 10, "avg_score": 8.0, "affinity": 0.7},
        ]
        result = _apply_deltas(affinity_list, {})
        assert result == affinity_list

    def test_applies_positive_delta(self):
        affinity_list = [
            {"genre": "Action", "count": 10, "avg_score": 8.0, "affinity": 0.5},
        ]
        result = _apply_deltas(affinity_list, {"Action": 0.1})
        assert result[0]["affinity"] == pytest.approx(0.6, abs=0.001)

    def test_applies_negative_delta(self):
        affinity_list = [
            {"genre": "Romance", "count": 5, "avg_score": 6.0, "affinity": 0.4},
        ]
        result = _apply_deltas(affinity_list, {"Romance": -0.1})
        assert result[0]["affinity"] == pytest.approx(0.3, abs=0.001)

    def test_clamps_to_max(self):
        affinity_list = [
            {"genre": "Action", "count": 10, "avg_score": 8.0, "affinity": 0.95},
        ]
        result = _apply_deltas(affinity_list, {"Action": 0.2})
        assert result[0]["affinity"] == MAX_AFFINITY

    def test_clamps_to_min(self):
        affinity_list = [
            {"genre": "Romance", "count": 5, "avg_score": 6.0, "affinity": 0.02},
        ]
        result = _apply_deltas(affinity_list, {"Romance": -0.1})
        assert result[0]["affinity"] == MIN_AFFINITY

    def test_adds_new_entry(self):
        """Delta for a genre not in the list should create a new entry."""
        affinity_list = [
            {"genre": "Action", "count": 10, "avg_score": 8.0, "affinity": 0.7},
        ]
        result = _apply_deltas(affinity_list, {"Horror": 0.05})

        genre_names = [g["genre"] for g in result]
        assert "Horror" in genre_names

        horror = next(g for g in result if g["genre"] == "Horror")
        assert horror["affinity"] == pytest.approx(0.35, abs=0.001)  # 0.3 base + 0.05
        assert horror["count"] == 0
        assert horror["avg_score"] == 0.0

    def test_does_not_mutate_input(self):
        """Input list should not be modified."""
        affinity_list = [
            {"genre": "Action", "count": 10, "avg_score": 8.0, "affinity": 0.7},
        ]
        original = copy.deepcopy(affinity_list)

        _apply_deltas(affinity_list, {"Action": 0.1})

        assert affinity_list[0]["affinity"] == original[0]["affinity"]
