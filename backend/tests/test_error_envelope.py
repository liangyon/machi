"""Tests for standardized API error envelope and request id propagation."""

from fastapi.testclient import TestClient


def test_error_envelope_on_unauthorized(client: TestClient) -> None:
    response = client.get("/api/recommendations")
    assert response.status_code == 401

    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == "UNAUTHORIZED"
    assert isinstance(payload["error"]["message"], str)
    assert payload["error"]["request_id"]
    assert response.headers.get("X-Request-ID")


def test_request_id_is_propagated_when_provided(client: TestClient) -> None:
    request_id = "test-request-id-123"
    response = client.get("/api/health", headers={"X-Request-ID": request_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == request_id
