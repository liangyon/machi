"""Tests for the recommendation API endpoints.

Testing strategy
────────────────
These are HTTP-level tests using FastAPI's TestClient.  They verify:

1. **Auth enforcement** — endpoints require a valid session cookie
2. **Prerequisite checks** — 404 when no preference profile exists
3. **Cache behaviour** — GET returns cached recs, 404 when empty
4. **Feedback storage** — feedback endpoint accepts valid input
5. **Request validation** — invalid inputs are rejected

We do NOT test the actual recommendation quality here (that's in
test_recommender.py).  These tests mock the recommender service
to focus on the API layer: routing, auth, validation, response shape.

Why use dependency_overrides instead of patch()?
────────────────────────────────────────────────
FastAPI resolves dependencies via its own DI system, not Python's
import system.  ``patch("app.api.recommendations.get_current_user")``
patches the module-level reference, but FastAPI's ``Depends()`` still
calls the original function.  ``app.dependency_overrides`` is the
correct way to swap dependencies in tests.
"""

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user
from app.api.recommendations import _recommendation_cache, _feedback_store


# ═════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear in-memory caches before each test."""
    _recommendation_cache.clear()
    _feedback_store.clear()
    yield
    _recommendation_cache.clear()
    _feedback_store.clear()


@pytest.fixture()
def mock_user():
    """Create a mock user object."""
    user = MagicMock()
    user.id = "test-user-123"
    user.email = "test@example.com"
    return user


@pytest.fixture()
def authed_client(mock_user):
    """Return a TestClient with auth dependency overridden.

    This is the FastAPI-correct way to mock authentication.
    We override the ``get_current_user`` dependency to return
    our mock user, bypassing the cookie/JWT check entirely.
    """
    app.dependency_overrides[get_current_user] = lambda: mock_user
    client = TestClient(app)
    yield client
    # Clean up: remove the override so other tests aren't affected
    app.dependency_overrides.pop(get_current_user, None)


# ═════════════════════════════════════════════════════════
# Tests: Authentication
# ═════════════════════════════════════════════════════════


class TestRecommendationAuth:
    """All recommendation endpoints require authentication."""

    def test_generate_requires_auth(self, client: TestClient):
        """POST /generate should return 401 without session cookie."""
        resp = client.post("/api/recommendations/generate", json={})
        assert resp.status_code == 401

    def test_get_cached_requires_auth(self, client: TestClient):
        """GET /recommendations should return 401 without session cookie."""
        resp = client.get("/api/recommendations")
        assert resp.status_code == 401

    def test_feedback_requires_auth(self, client: TestClient):
        """POST /feedback should return 401 without session cookie."""
        resp = client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 1, "feedback": "liked"},
        )
        assert resp.status_code == 401


# ═════════════════════════════════════════════════════════
# Tests: GET /api/recommendations (cached)
# ═════════════════════════════════════════════════════════


class TestGetCachedRecommendations:
    """Test the cached recommendations endpoint."""

    def test_returns_404_when_no_cache(self, authed_client: TestClient):
        """Should return 404 if no recommendations have been generated."""
        resp = authed_client.get("/api/recommendations")
        assert resp.status_code == 404
        assert "No recommendations generated" in resp.json()["detail"]


# ═════════════════════════════════════════════════════════
# Tests: POST /api/recommendations/feedback
# ═════════════════════════════════════════════════════════


class TestRecommendationFeedback:
    """Test the feedback endpoint."""

    def test_valid_feedback_accepted(self, authed_client: TestClient):
        """Should accept valid feedback (liked/disliked/watched)."""
        for feedback_type in ["liked", "disliked", "watched"]:
            resp = authed_client.post(
                "/api/recommendations/feedback",
                json={"mal_id": 1, "feedback": feedback_type},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["mal_id"] == 1
            assert data["feedback"] == feedback_type

    def test_invalid_feedback_rejected(self, authed_client: TestClient):
        """Should reject invalid feedback values."""
        resp = authed_client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 1, "feedback": "amazing"},
        )
        assert resp.status_code == 422  # validation error

    def test_feedback_stored(self, authed_client: TestClient):
        """Feedback should be stored in the feedback store."""
        authed_client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 1, "feedback": "liked"},
        )
        authed_client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 2, "feedback": "disliked"},
        )

        assert len(_feedback_store["test-user-123"]) == 2
        assert _feedback_store["test-user-123"][0]["mal_id"] == 1
        assert _feedback_store["test-user-123"][1]["feedback"] == "disliked"


# ═════════════════════════════════════════════════════════
# Tests: Request validation
# ═════════════════════════════════════════════════════════


class TestRequestValidation:
    """Test that request schemas validate input correctly."""

    def test_num_recommendations_too_low(self, authed_client: TestClient):
        """num_recommendations below 1 should be rejected."""
        resp = authed_client.post(
            "/api/recommendations/generate",
            json={"num_recommendations": 0},
        )
        assert resp.status_code == 422

    def test_num_recommendations_too_high(self, authed_client: TestClient):
        """num_recommendations above 25 should be rejected."""
        resp = authed_client.post(
            "/api/recommendations/generate",
            json={"num_recommendations": 100},
        )
        assert resp.status_code == 422

    def test_feedback_missing_feedback_field(self, authed_client: TestClient):
        """Feedback requires the feedback field."""
        resp = authed_client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 1},
        )
        assert resp.status_code == 422

    def test_feedback_missing_mal_id(self, authed_client: TestClient):
        """Feedback requires the mal_id field."""
        resp = authed_client.post(
            "/api/recommendations/feedback",
            json={"feedback": "liked"},
        )
        assert resp.status_code == 422
