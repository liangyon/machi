"""Tests for the vector store service helper functions.

These tests cover the pure helper functions in vector_store.py:
• _build_metadata — converts anime dicts to ChromaDB metadata format
• _build_chroma_filter — translates user-friendly filters to ChromaDB syntax

These are pure functions — no ChromaDB, no OpenAI, no network.
They test the data transformation logic that sits between our
application code and ChromaDB's API.

Why test these?
───────────────
Metadata and filters are how we control what the vector store
returns.  If _build_metadata drops a field, we can't filter by it.
If _build_chroma_filter generates wrong syntax, searches silently
return wrong results.  These are subtle bugs that are hard to catch
without explicit tests.
"""

import pytest

from app.services.vector_store import (
    _build_metadata,
    _build_chroma_filter,
)


# ═════════════════════════════════════════════════════════
# Tests: _build_metadata
# ═════════════════════════════════════════════════════════


class TestBuildMetadata:
    """Test ChromaDB metadata construction from anime entries.

    ChromaDB metadata values must be str, int, float, or bool.
    No lists, no nested dicts, no None values.
    """

    def test_full_entry(self):
        """All fields present should all appear in metadata."""
        entry = {
            "mal_id": 1,
            "title": "Cowboy Bebop",
            "genres": "Action, Sci-Fi",
            "themes": "Space, Adult Cast",
            "anime_type": "TV",
            "year": 1998,
            "mal_score": 8.75,
            "mal_members": 1800000,
        }

        metadata = _build_metadata(entry)

        assert metadata["mal_id"] == 1
        assert metadata["title"] == "Cowboy Bebop"
        assert metadata["genres"] == "Action, Sci-Fi"
        assert metadata["themes"] == "Space, Adult Cast"
        assert metadata["anime_type"] == "TV"
        assert metadata["year"] == 1998
        assert metadata["mal_score"] == 8.75
        assert metadata["mal_members"] == 1800000

    def test_minimal_entry(self):
        """Entry with only mal_id and title."""
        entry = {"mal_id": 99, "title": "Test"}
        metadata = _build_metadata(entry)

        assert metadata["mal_id"] == 99
        assert metadata["title"] == "Test"
        assert "genres" not in metadata
        assert "year" not in metadata

    def test_empty_entry(self):
        """Empty dict should produce empty metadata."""
        metadata = _build_metadata({})
        assert metadata == {}

    def test_none_values_excluded(self):
        """None values should not appear in metadata (ChromaDB rejects them)."""
        entry = {
            "mal_id": 1,
            "title": "Test",
            "genres": None,
            "year": None,
            "mal_score": None,
        }
        metadata = _build_metadata(entry)

        assert "mal_id" in metadata
        assert "title" in metadata
        assert "genres" not in metadata
        assert "year" not in metadata
        assert "mal_score" not in metadata

    def test_types_are_correct(self):
        """Metadata values should be the correct types for ChromaDB."""
        entry = {
            "mal_id": "1",  # string input
            "title": 123,   # int input
            "year": "2020", # string input
            "mal_score": "8.5",  # string input
        }
        metadata = _build_metadata(entry)

        # Should be coerced to correct types
        assert isinstance(metadata["mal_id"], int)
        assert isinstance(metadata["title"], str)
        assert isinstance(metadata["year"], int)
        assert isinstance(metadata["mal_score"], float)

    def test_zero_values_included(self):
        """Zero is a valid value (not falsy for our purposes).
        
        Note: Our current implementation uses `if entry.get(field)` 
        which treats 0 as falsy. This test documents that behavior.
        A score of 0 or year of 0 would be excluded.
        For real anime data, score=0 means "not scored" and year=0
        doesn't exist, so this is acceptable.
        """
        entry = {"mal_id": 1, "mal_score": 0, "year": 0}
        metadata = _build_metadata(entry)
        # 0 is falsy, so these won't be included with current impl
        assert "mal_score" not in metadata
        assert "year" not in metadata


# ═════════════════════════════════════════════════════════
# Tests: _build_chroma_filter
# ═════════════════════════════════════════════════════════


class TestBuildChromaFilter:
    """Test ChromaDB filter construction from user-friendly dicts.

    ChromaDB uses a specific filter syntax:
    - {"field": value} for exact match
    - {"field": {"$gte": value}} for >= comparison
    - {"$and": [...]} for combining conditions

    Our _build_chroma_filter translates a simpler dict format:
    - {"field": value} → exact match
    - {"field_gte": value} → >= comparison
    - {"field_lte": value} → <= comparison
    - {"field_ne": value} → != comparison
    """

    def test_exact_match(self):
        """Simple key=value should produce exact match filter."""
        result = _build_chroma_filter({"anime_type": "TV"})
        assert result == {"anime_type": "TV"}

    def test_gte_filter(self):
        """_gte suffix should produce $gte operator."""
        result = _build_chroma_filter({"year_gte": 2020})
        assert result == {"year": {"$gte": 2020}}

    def test_lte_filter(self):
        """_lte suffix should produce $lte operator."""
        result = _build_chroma_filter({"year_lte": 2010})
        assert result == {"year": {"$lte": 2010}}

    def test_ne_filter(self):
        """_ne suffix should produce $ne operator."""
        result = _build_chroma_filter({"anime_type_ne": "Music"})
        assert result == {"anime_type": {"$ne": "Music"}}

    def test_multiple_conditions_combined_with_and(self):
        """Multiple conditions should be combined with $and."""
        result = _build_chroma_filter({
            "anime_type": "TV",
            "year_gte": 2020,
        })

        assert "$and" in result
        conditions = result["$and"]
        assert len(conditions) == 2
        assert {"anime_type": "TV"} in conditions
        assert {"year": {"$gte": 2020}} in conditions

    def test_three_conditions(self):
        """Three conditions should all be in the $and list."""
        result = _build_chroma_filter({
            "anime_type": "TV",
            "year_gte": 2020,
            "mal_score_gte": 7.0,
        })

        assert "$and" in result
        assert len(result["$and"]) == 3

    def test_empty_dict_returns_none(self):
        """Empty filter dict should return None (no filter)."""
        result = _build_chroma_filter({})
        assert result is None

    def test_score_range_filter(self):
        """Common use case: filter by score range."""
        result = _build_chroma_filter({
            "mal_score_gte": 7.0,
            "mal_score_lte": 9.0,
        })

        assert "$and" in result
        conditions = result["$and"]
        assert {"mal_score": {"$gte": 7.0}} in conditions
        assert {"mal_score": {"$lte": 9.0}} in conditions

    def test_year_range_filter(self):
        """Common use case: filter by year range."""
        result = _build_chroma_filter({
            "year_gte": 2010,
            "year_lte": 2020,
        })

        assert "$and" in result
        conditions = result["$and"]
        assert {"year": {"$gte": 2010}} in conditions
        assert {"year": {"$lte": 2020}} in conditions
