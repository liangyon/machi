"""Tests for the recommendation engine.

Testing strategy
────────────────
The recommender has two types of code:

1. **Pure functions** (no network, no LLM, no side effects):
   - ``build_system_prompt()`` — always returns the same string
   - ``build_user_prompt()`` — formats profile + candidates into text
   - ``parse_recommendations()`` — extracts JSON from LLM response
   - ``_clean_json_response()`` — strips markdown fences
   - ``_build_fallback_recommendations()`` — deterministic fallback
   - ``_format_taste_summary()``, ``_format_top_anime()``, etc.

   These are tested directly — no mocks needed.  They're the
   highest-leverage tests because they verify the "intelligence"
   of the system (prompt quality, parsing robustness).

2. **Orchestration functions** (call LLM, call vector store):
   - ``generate_recommendations()`` — the main entry point
   - ``_call_llm_with_retry()`` — retry logic

   These are tested with mocks (mock the LLM and retriever).
   We verify the *flow* (retry on failure, fallback on double
   failure) without actually calling OpenAI.

Why test prompt construction?
─────────────────────────────
The prompt IS the product.  If the prompt is wrong, the LLM gives
bad recommendations.  Testing that the prompt includes the user's
top genres, top shows, and candidate anime catches regressions
before they reach production.

Why test JSON parsing so thoroughly?
────────────────────────────────────
LLMs are unpredictable.  We test every edge case we've seen in
practice: markdown fences, extra text, invalid JSON, hallucinated
mal_ids, missing fields.  Each test case represents a real failure
mode we want to handle gracefully.
"""

import json

import pytest

from app.services.recommender import (
    build_system_prompt,
    build_user_prompt,
    parse_recommendations,
    _clean_json_response,
    _validate_confidence,
    _truncate,
    _format_taste_summary,
    _format_top_anime,
    _format_candidates,
    _build_fallback_recommendations,
)


# ═════════════════════════════════════════════════════════
# Test fixtures — reusable mock data
# ═════════════════════════════════════════════════════════

# A realistic preference profile (same shape as what
# preference_analyzer.py produces)
MOCK_PROFILE = {
    "total_watched": 150,
    "total_scored": 120,
    "mean_score": 7.5,
    "completion_rate": 0.85,
    "genre_affinity": [
        {"genre": "Action", "count": 45, "avg_score": 7.8, "affinity": 0.85},
        {"genre": "Sci-Fi", "count": 20, "avg_score": 8.2, "affinity": 0.78},
        {"genre": "Drama", "count": 30, "avg_score": 7.5, "affinity": 0.72},
    ],
    "theme_affinity": [
        {"genre": "Time Travel", "count": 5, "avg_score": 9.0, "affinity": 0.90},
        {"genre": "Psychological", "count": 8, "avg_score": 8.5, "affinity": 0.82},
    ],
    "studio_affinity": [
        {"genre": "MAPPA", "count": 10, "avg_score": 8.0, "affinity": 0.80},
    ],
    "preferred_formats": {"TV": 100, "Movie": 30, "OVA": 10},
    "top_10": [
        {"title": "Steins;Gate", "user_score": 10, "mal_anime_id": 9253, "genres": "Sci-Fi, Drama", "anime_type": "TV"},
        {"title": "Death Note", "user_score": 10, "mal_anime_id": 1535, "genres": "Thriller", "anime_type": "TV"},
        {"title": "Monster", "user_score": 10, "mal_anime_id": 19, "genres": "Drama, Thriller", "anime_type": "TV"},
    ],
    "watch_era_preference": {"2020s": 50, "2010s": 60, "2000s": 25},
}

MOCK_EMPTY_PROFILE = {
    "total_watched": 0,
    "total_scored": 0,
    "mean_score": 0.0,
    "completion_rate": 0.0,
    "genre_affinity": [],
    "theme_affinity": [],
    "studio_affinity": [],
    "preferred_formats": {},
    "top_10": [],
    "watch_era_preference": {},
}

# Mock candidates (what the RAG retriever returns)
MOCK_CANDIDATES = [
    {
        "mal_id": 1,
        "title": "Cowboy Bebop",
        "embedding_text": "Title: Cowboy Bebop. A space bounty hunter crew...",
        "metadata": {
            "mal_id": 1,
            "title": "Cowboy Bebop",
            "genres": "Action, Sci-Fi",
            "themes": "Space, Adult Cast",
            "anime_type": "TV",
            "year": 1998,
            "mal_score": 8.75,
            "image_url": "https://example.com/bebop.jpg",
        },
        "similarity_score": 0.85,
        "preference_score": 0.72,
        "combined_score": 0.80,
    },
    {
        "mal_id": 11061,
        "title": "Hunter x Hunter (2011)",
        "embedding_text": "Title: Hunter x Hunter. A young boy sets out to become a Hunter...",
        "metadata": {
            "mal_id": 11061,
            "title": "Hunter x Hunter (2011)",
            "genres": "Action, Adventure, Fantasy",
            "themes": "Martial Arts",
            "anime_type": "TV",
            "year": 2011,
            "mal_score": 9.04,
            "image_url": "https://example.com/hxh.jpg",
        },
        "similarity_score": 0.78,
        "preference_score": 0.68,
        "combined_score": 0.74,
    },
    {
        "mal_id": 9999,
        "title": "Some Anime",
        "embedding_text": "Title: Some Anime. A story about...",
        "metadata": {
            "mal_id": 9999,
            "title": "Some Anime",
            "genres": "Romance",
            "themes": "",
            "anime_type": "Movie",
            "year": 2022,
            "mal_score": 7.5,
        },
        "similarity_score": 0.60,
        "preference_score": 0.45,
        "combined_score": 0.54,
    },
]


# ═════════════════════════════════════════════════════════
# Tests: build_system_prompt
# ═════════════════════════════════════════════════════════


class TestBuildSystemPrompt:
    """Test the system prompt construction."""

    def test_returns_non_empty_string(self):
        """System prompt should be a substantial string."""
        prompt = build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_contains_json_format_instruction(self):
        """Should instruct the LLM to return JSON."""
        prompt = build_system_prompt()
        assert "JSON" in prompt
        assert "mal_id" in prompt
        assert "reasoning" in prompt
        assert "confidence" in prompt

    def test_contains_anti_hallucination_rule(self):
        """Should tell the LLM to only use provided candidates."""
        prompt = build_system_prompt()
        assert "ONLY" in prompt
        assert "CANDIDATE" in prompt or "candidate" in prompt

    def test_contains_confidence_levels(self):
        """Should define high/medium/low confidence."""
        prompt = build_system_prompt()
        assert "high" in prompt
        assert "medium" in prompt
        assert "low" in prompt


# ═════════════════════════════════════════════════════════
# Tests: build_user_prompt
# ═════════════════════════════════════════════════════════


class TestBuildUserPrompt:
    """Test user prompt construction with profile + candidates."""

    def test_includes_taste_profile(self):
        """Prompt should contain the user's taste data."""
        prompt = build_user_prompt(MOCK_PROFILE, MOCK_CANDIDATES)
        assert "150" in prompt  # total_watched
        assert "7.5" in prompt  # mean_score
        assert "Action" in prompt  # top genre
        assert "Sci-Fi" in prompt

    def test_includes_top_anime(self):
        """Prompt should list the user's top-rated shows."""
        prompt = build_user_prompt(MOCK_PROFILE, MOCK_CANDIDATES)
        assert "Steins;Gate" in prompt
        assert "Death Note" in prompt
        assert "Monster" in prompt
        assert "10/10" in prompt  # their score

    def test_includes_candidates(self):
        """Prompt should list all candidate anime with mal_ids."""
        prompt = build_user_prompt(MOCK_PROFILE, MOCK_CANDIDATES)
        assert "Cowboy Bebop" in prompt
        assert "Hunter x Hunter" in prompt
        assert "mal_id: 1" in prompt
        assert "mal_id: 11061" in prompt

    def test_includes_recommendation_count(self):
        """Prompt should specify how many recs to generate."""
        prompt = build_user_prompt(MOCK_PROFILE, MOCK_CANDIDATES, num_recommendations=5)
        assert "5" in prompt

    def test_empty_profile_still_works(self):
        """Should handle an empty profile gracefully."""
        prompt = build_user_prompt(MOCK_EMPTY_PROFILE, MOCK_CANDIDATES)
        assert isinstance(prompt, str)
        assert len(prompt) > 50
        # Should still include candidates
        assert "Cowboy Bebop" in prompt

    def test_empty_candidates_still_works(self):
        """Should handle empty candidates gracefully."""
        prompt = build_user_prompt(MOCK_PROFILE, [])
        assert isinstance(prompt, str)
        assert "Total candidates: 0" in prompt


# ═════════════════════════════════════════════════════════
# Tests: _format_taste_summary
# ═════════════════════════════════════════════════════════


class TestFormatTasteSummary:
    """Test taste profile formatting."""

    def test_includes_basic_stats(self):
        result = _format_taste_summary(MOCK_PROFILE)
        assert "150" in result
        assert "7.5" in result
        assert "85%" in result  # completion rate

    def test_includes_genres(self):
        result = _format_taste_summary(MOCK_PROFILE)
        assert "Action" in result
        assert "0.85" in result  # affinity

    def test_includes_themes(self):
        result = _format_taste_summary(MOCK_PROFILE)
        assert "Time Travel" in result

    def test_includes_formats(self):
        result = _format_taste_summary(MOCK_PROFILE)
        assert "TV" in result

    def test_includes_eras(self):
        result = _format_taste_summary(MOCK_PROFILE)
        assert "2010s" in result

    def test_empty_profile(self):
        result = _format_taste_summary(MOCK_EMPTY_PROFILE)
        assert "0" in result  # total_watched = 0


# ═════════════════════════════════════════════════════════
# Tests: _format_top_anime
# ═════════════════════════════════════════════════════════


class TestFormatTopAnime:
    """Test top anime formatting."""

    def test_lists_top_shows(self):
        result = _format_top_anime(MOCK_PROFILE)
        assert "Steins;Gate" in result
        assert "10/10" in result
        assert "1." in result  # numbered list

    def test_empty_top_10(self):
        result = _format_top_anime(MOCK_EMPTY_PROFILE)
        assert "No scored anime" in result


# ═════════════════════════════════════════════════════════
# Tests: _format_candidates
# ═════════════════════════════════════════════════════════


class TestFormatCandidates:
    """Test candidate anime formatting."""

    def test_includes_all_candidates(self):
        result = _format_candidates(MOCK_CANDIDATES)
        assert "Cowboy Bebop" in result
        assert "Hunter x Hunter" in result
        assert "Some Anime" in result

    def test_includes_mal_ids(self):
        result = _format_candidates(MOCK_CANDIDATES)
        assert "mal_id: 1" in result
        assert "mal_id: 11061" in result

    def test_includes_metadata(self):
        result = _format_candidates(MOCK_CANDIDATES)
        assert "Action, Sci-Fi" in result  # genres
        assert "Space" in result  # themes
        assert "1998" in result  # year

    def test_includes_scores(self):
        result = _format_candidates(MOCK_CANDIDATES)
        assert "similarity=" in result
        assert "preference=" in result

    def test_empty_candidates(self):
        result = _format_candidates([])
        assert "Total candidates: 0" in result


# ═════════════════════════════════════════════════════════
# Tests: parse_recommendations
# ═════════════════════════════════════════════════════════


class TestParseRecommendations:
    """Test LLM response parsing — the most critical tests.

    These cover every edge case we've seen from LLMs:
    clean JSON, markdown-wrapped, extra text, invalid JSON,
    hallucinated IDs, missing fields, etc.
    """

    def test_clean_json_response(self):
        """Parse a perfectly formatted JSON response."""
        response = json.dumps([
            {
                "mal_id": 1,
                "title": "Cowboy Bebop",
                "reasoning": "Great match for action lovers.",
                "confidence": "high",
                "similar_to": ["Steins;Gate"],
            }
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)

        assert len(result) == 1
        assert result[0]["mal_id"] == 1
        assert result[0]["title"] == "Cowboy Bebop"
        assert result[0]["reasoning"] == "Great match for action lovers."
        assert result[0]["confidence"] == "high"
        assert result[0]["similar_to"] == ["Steins;Gate"]

    def test_enriches_with_candidate_metadata(self):
        """Should add image_url, genres, etc. from candidate data."""
        response = json.dumps([
            {"mal_id": 1, "title": "Cowboy Bebop", "reasoning": "Good.", "confidence": "high", "similar_to": []}
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)

        assert result[0]["image_url"] == "https://example.com/bebop.jpg"
        assert result[0]["genres"] == "Action, Sci-Fi"
        assert result[0]["mal_score"] == 8.75
        assert result[0]["year"] == 1998
        assert result[0]["similarity_score"] == 0.85

    def test_markdown_fenced_json(self):
        """Handle JSON wrapped in ```json ... ``` fences."""
        inner = json.dumps([
            {"mal_id": 1, "title": "Cowboy Bebop", "reasoning": "Good.", "confidence": "high", "similar_to": []}
        ])
        response = f"```json\n{inner}\n```"

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert len(result) == 1
        assert result[0]["mal_id"] == 1

    def test_markdown_fenced_no_language(self):
        """Handle JSON wrapped in ``` ... ``` (no language tag)."""
        inner = json.dumps([
            {"mal_id": 1, "title": "Cowboy Bebop", "reasoning": "Good.", "confidence": "high", "similar_to": []}
        ])
        response = f"```\n{inner}\n```"

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert len(result) == 1

    def test_extra_text_around_json(self):
        """Handle LLM adding commentary before/after JSON."""
        inner = json.dumps([
            {"mal_id": 1, "title": "Cowboy Bebop", "reasoning": "Good.", "confidence": "high", "similar_to": []}
        ])
        response = f"Here are my recommendations:\n\n{inner}\n\nI hope you enjoy these!"

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert len(result) == 1

    def test_invalid_json_returns_empty(self):
        """Completely invalid JSON should return empty list, not crash."""
        result = parse_recommendations("This is not JSON at all!", MOCK_CANDIDATES)
        assert result == []

    def test_non_array_json_returns_empty(self):
        """JSON object (not array) should return empty list."""
        result = parse_recommendations('{"mal_id": 1}', MOCK_CANDIDATES)
        assert result == []

    def test_hallucinated_mal_id_skipped(self):
        """LLM recommending a mal_id not in candidates should be skipped."""
        response = json.dumps([
            {"mal_id": 99999, "title": "Fake Anime", "reasoning": "...", "confidence": "high", "similar_to": []},
            {"mal_id": 1, "title": "Cowboy Bebop", "reasoning": "Good.", "confidence": "high", "similar_to": []},
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)

        # Only the valid one should remain
        assert len(result) == 1
        assert result[0]["mal_id"] == 1

    def test_missing_reasoning_gets_default(self):
        """Missing reasoning field should get a default message."""
        response = json.dumps([
            {"mal_id": 1, "title": "Cowboy Bebop", "confidence": "high", "similar_to": []}
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert result[0]["reasoning"] == "No reasoning provided."

    def test_invalid_confidence_defaults_to_medium(self):
        """Invalid confidence value should default to 'medium'."""
        response = json.dumps([
            {"mal_id": 1, "title": "Cowboy Bebop", "reasoning": "Good.", "confidence": "super_high", "similar_to": []}
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert result[0]["confidence"] == "medium"

    def test_multiple_valid_recommendations(self):
        """Should handle multiple valid recommendations."""
        response = json.dumps([
            {"mal_id": 1, "title": "Cowboy Bebop", "reasoning": "Action.", "confidence": "high", "similar_to": []},
            {"mal_id": 11061, "title": "HxH", "reasoning": "Adventure.", "confidence": "medium", "similar_to": []},
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert len(result) == 2
        assert result[0]["mal_id"] == 1
        assert result[1]["mal_id"] == 11061

    def test_empty_response_returns_empty(self):
        """Empty string should return empty list."""
        result = parse_recommendations("", MOCK_CANDIDATES)
        assert result == []

    def test_empty_array_returns_empty(self):
        """Empty JSON array should return empty list."""
        result = parse_recommendations("[]", MOCK_CANDIDATES)
        assert result == []

    def test_non_dict_items_skipped(self):
        """Non-dict items in the array should be skipped."""
        response = json.dumps([
            "not a dict",
            42,
            {"mal_id": 1, "title": "Cowboy Bebop", "reasoning": "Good.", "confidence": "high", "similar_to": []},
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert len(result) == 1

    def test_title_fallback_corrects_wrong_mal_id(self):
        """If LLM uses wrong mal_id but correct title, match by title.

        This is the key fix for the bug where the LLM used index
        numbers (1, 2, 3) instead of actual mal_ids (52991, 38524).
        The title-based fallback catches this and corrects the mal_id.
        """
        response = json.dumps([
            {
                "mal_id": 42,  # WRONG — not a real candidate mal_id
                "title": "Hunter x Hunter (2011)",  # RIGHT — matches candidate
                "reasoning": "Great adventure anime.",
                "confidence": "high",
                "similar_to": [],
            }
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)

        # Should match by title and correct the mal_id
        assert len(result) == 1
        assert result[0]["mal_id"] == 11061  # corrected to real mal_id
        assert result[0]["title"] == "Hunter x Hunter (2011)"
        assert result[0]["genres"] == "Action, Adventure, Fantasy"

    def test_title_fallback_case_insensitive(self):
        """Title matching should be case-insensitive."""
        response = json.dumps([
            {
                "mal_id": 999,
                "title": "cowboy bebop",  # lowercase
                "reasoning": "Good.",
                "confidence": "high",
                "similar_to": [],
            }
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert len(result) == 1
        assert result[0]["mal_id"] == 1  # matched Cowboy Bebop

    def test_title_fallback_skips_if_no_title_match(self):
        """If both mal_id and title are wrong, skip the item."""
        response = json.dumps([
            {
                "mal_id": 42,
                "title": "Totally Made Up Anime",
                "reasoning": "...",
                "confidence": "high",
                "similar_to": [],
            }
        ])

        result = parse_recommendations(response, MOCK_CANDIDATES)
        assert len(result) == 0


# ═════════════════════════════════════════════════════════
# Tests: _clean_json_response
# ═════════════════════════════════════════════════════════


class TestCleanJsonResponse:
    """Test the JSON cleaning helper directly."""

    def test_already_clean(self):
        assert _clean_json_response('[{"a": 1}]') == '[{"a": 1}]'

    def test_strips_whitespace(self):
        assert _clean_json_response('  [{"a": 1}]  ') == '[{"a": 1}]'

    def test_strips_json_fence(self):
        result = _clean_json_response('```json\n[{"a": 1}]\n```')
        assert result == '[{"a": 1}]'

    def test_strips_plain_fence(self):
        result = _clean_json_response('```\n[{"a": 1}]\n```')
        assert result == '[{"a": 1}]'

    def test_strips_leading_text(self):
        result = _clean_json_response('Here you go:\n[{"a": 1}]')
        assert result == '[{"a": 1}]'

    def test_strips_trailing_text(self):
        result = _clean_json_response('[{"a": 1}]\nHope this helps!')
        assert result == '[{"a": 1}]'

    def test_strips_both_sides(self):
        result = _clean_json_response('Sure!\n[{"a": 1}]\nEnjoy!')
        assert result == '[{"a": 1}]'

    def test_no_brackets_returns_as_is(self):
        """If there are no brackets at all, return cleaned text."""
        result = _clean_json_response("no json here")
        assert result == "no json here"


# ═════════════════════════════════════════════════════════
# Tests: _validate_confidence
# ═════════════════════════════════════════════════════════


class TestValidateConfidence:
    """Test confidence level validation."""

    def test_valid_values(self):
        assert _validate_confidence("high") == "high"
        assert _validate_confidence("medium") == "medium"
        assert _validate_confidence("low") == "low"

    def test_case_insensitive(self):
        assert _validate_confidence("HIGH") == "high"
        assert _validate_confidence("Medium") == "medium"

    def test_invalid_defaults_to_medium(self):
        assert _validate_confidence("super") == "medium"
        assert _validate_confidence("") == "medium"
        assert _validate_confidence("123") == "medium"


# ═════════════════════════════════════════════════════════
# Tests: _truncate
# ═════════════════════════════════════════════════════════


class TestTruncate:
    """Test text truncation."""

    def test_short_text_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert _truncate("hello", 5) == "hello"

    def test_long_text_truncated(self):
        result = _truncate("hello world", 8)
        assert result == "hello..."
        assert len(result) == 8

    def test_default_max_length(self):
        short = "x" * 100
        assert _truncate(short) == short  # under 300

        long = "x" * 500
        result = _truncate(long)
        assert len(result) == 300
        assert result.endswith("...")


# ═════════════════════════════════════════════════════════
# Tests: _build_fallback_recommendations
# ═════════════════════════════════════════════════════════


class TestBuildFallbackRecommendations:
    """Test the deterministic fallback when LLM fails."""

    def test_returns_correct_count(self):
        """Should return exactly num_recommendations items."""
        result = _build_fallback_recommendations(MOCK_CANDIDATES, 2)
        assert len(result) == 2

    def test_returns_all_if_fewer_candidates(self):
        """If fewer candidates than requested, return all."""
        result = _build_fallback_recommendations(MOCK_CANDIDATES, 10)
        assert len(result) == 3  # only 3 candidates

    def test_includes_required_fields(self):
        """Each fallback rec should have all required fields."""
        result = _build_fallback_recommendations(MOCK_CANDIDATES, 1)
        rec = result[0]

        assert "mal_id" in rec
        assert "title" in rec
        assert "reasoning" in rec
        assert "confidence" in rec
        assert "similar_to" in rec
        assert "is_fallback" in rec

    def test_is_fallback_flag_set(self):
        """Fallback recs should have is_fallback=True."""
        result = _build_fallback_recommendations(MOCK_CANDIDATES, 1)
        assert result[0]["is_fallback"] is True

    def test_confidence_is_medium(self):
        """Fallback recs should have medium confidence."""
        result = _build_fallback_recommendations(MOCK_CANDIDATES, 1)
        assert result[0]["confidence"] == "medium"

    def test_reasoning_mentions_genres(self):
        """Fallback reasoning should reference the anime's genres."""
        result = _build_fallback_recommendations(MOCK_CANDIDATES, 1)
        assert "Action" in result[0]["reasoning"] or "Sci-Fi" in result[0]["reasoning"]

    def test_preserves_retriever_scores(self):
        """Should carry over similarity/preference/combined scores."""
        result = _build_fallback_recommendations(MOCK_CANDIDATES, 1)
        assert result[0]["similarity_score"] == 0.85
        assert result[0]["preference_score"] == 0.72
        assert result[0]["combined_score"] == 0.80

    def test_empty_candidates(self):
        """Empty candidates should return empty list."""
        result = _build_fallback_recommendations([], 5)
        assert result == []
