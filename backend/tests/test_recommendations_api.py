"""Tests for the recommendation API endpoints — Phase 3.5 (persistent).

Testing strategy
────────────────
These are HTTP-level tests using FastAPI's TestClient.  They verify:

1. **Auth enforcement** — endpoints require a valid session cookie
2. **Prerequisite checks** — 404 when no preference profile exists
3. **DB persistence** — GET returns recs from DB, 404 when empty
4. **Feedback storage** — feedback endpoint accepts valid input, persists to DB
5. **Request validation** — invalid inputs are rejected

We do NOT test the actual recommendation quality here (that's in
test_recommender.py).  These tests mock the recommender service
to focus on the API layer: routing, auth, validation, response shape.

Phase 3.5 changes:
- Removed in-memory cache references (_recommendation_cache, _feedback_store)
- Tests now use the database via the test DB session
- Feedback tests verify DB persistence instead of dict storage
"""

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import get_current_user, get_db
from app.db.session import Base

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ═════════════════════════════════════════════════════════
# Test database setup
# ═════════════════════════════════════════════════════════

TEST_DATABASE_URL = "sqlite:///./test_recommendations.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Provide a test database session."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ═════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def mock_user():
    """Create a mock user object."""
    user = MagicMock()
    user.id = "test-user-123"
    user.email = "test@example.com"
    return user


@pytest.fixture()
def authed_client(mock_user):
    """Return a TestClient with auth and DB dependencies overridden."""
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


# ═════════════════════════════════════════════════════════
# Tests: Authentication
# ═════════════════════════════════════════════════════════


class TestRecommendationAuth:
    """All recommendation endpoints require authentication."""

    def test_generate_requires_auth(self):
        """POST /generate should return 401 without session cookie."""
        # Use a client without auth override
        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        resp = client.post("/api/recommendations/generate", json={})
        assert resp.status_code == 401
        app.dependency_overrides.pop(get_db, None)

    def test_get_cached_requires_auth(self):
        """GET /recommendations should return 401 without session cookie."""
        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        resp = client.get("/api/recommendations")
        assert resp.status_code == 401
        app.dependency_overrides.pop(get_db, None)

    def test_feedback_requires_auth(self):
        """POST /feedback should return 401 without session cookie."""
        app.dependency_overrides[get_db] = override_get_db
        client = TestClient(app)
        resp = client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 1, "feedback": "liked"},
        )
        assert resp.status_code == 401
        app.dependency_overrides.pop(get_db, None)


# ═════════════════════════════════════════════════════════
# Tests: GET /api/recommendations (from DB)
# ═════════════════════════════════════════════════════════


class TestGetCachedRecommendations:
    """Test the cached recommendations endpoint."""

    def test_returns_404_when_no_recs(self, authed_client: TestClient):
        """Should return 404 if no recommendations have been generated."""
        resp = authed_client.get("/api/recommendations")
        assert resp.status_code == 404
        payload = resp.json()
        assert payload["error"]["code"] == "NOT_FOUND"
        assert "No recommendations generated" in payload["error"]["message"]
        assert payload["error"]["request_id"]
        assert resp.headers.get("X-Request-ID")


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

    def test_feedback_persisted_to_db(self, authed_client: TestClient):
        """Feedback should be persisted and retrievable via GET /feedback."""
        authed_client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 1, "feedback": "liked"},
        )
        authed_client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 2, "feedback": "disliked"},
        )

        resp = authed_client.get("/api/recommendations/feedback")
        assert resp.status_code == 200
        data = resp.json()
        assert data["feedback"]["1"] == "liked"
        assert data["feedback"]["2"] == "disliked"

    def test_feedback_upsert(self, authed_client: TestClient):
        """Submitting feedback for the same anime should update, not duplicate."""
        authed_client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 1, "feedback": "liked"},
        )
        authed_client.post(
            "/api/recommendations/feedback",
            json={"mal_id": 1, "feedback": "disliked"},
        )

        resp = authed_client.get("/api/recommendations/feedback")
        assert resp.status_code == 200
        data = resp.json()
        # Should have the latest feedback, not both
        assert data["feedback"]["1"] == "disliked"


# ═════════════════════════════════════════════════════════
# Tests: GET /api/recommendations/history
# ═════════════════════════════════════════════════════════


class TestRecommendationHistory:
    """Test the history endpoint."""

    def test_empty_history(self, authed_client: TestClient):
        """Should return empty list when no sessions exist."""
        resp = authed_client.get("/api/recommendations/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"] == []
        assert data["total"] == 0


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

    def test_guardrail_max_recommendations_enforced(self, authed_client: TestClient, monkeypatch):
        """Configured max recommendations should be enforced even within schema range."""
        monkeypatch.setattr("app.api.recommendations.settings.RECOMMEND_MAX_ITEMS_PER_REQUEST", 5)
        resp = authed_client.post(
            "/api/recommendations/generate",
            json={"num_recommendations": 6},
        )
        assert resp.status_code == 422
        payload = resp.json()
        assert payload["error"]["code"] == "VALIDATION_ERROR"

    def test_guardrail_custom_query_len_enforced(self, authed_client: TestClient, monkeypatch):
        monkeypatch.setattr("app.api.recommendations.settings.RECOMMEND_MAX_CUSTOM_QUERY_CHARS", 10)
        resp = authed_client.post(
            "/api/recommendations/generate",
            json={"custom_query": "this query is definitely too long"},
        )
        assert resp.status_code == 422
        payload = resp.json()
        assert payload["error"]["code"] == "VALIDATION_ERROR"
