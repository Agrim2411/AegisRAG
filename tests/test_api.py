from fastapi.testclient import TestClient

from aegis_rag.api import create_app
from aegis_rag.config import Settings


def test_api_contract_and_request_id(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "aegis_rag.api.get_settings",
        lambda: Settings(database_url=f"sqlite:///{tmp_path / 'api.db'}"),
    )
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["status"] == "ok"

    missing_tenant = client.post("/v1/query", json={"question": "hello"})
    assert missing_tenant.status_code == 400

    ingest = client.post(
        "/v1/ingest",
        headers={"x-tenant-id": "acme"},
        json={
            "title": "Policy",
            "source_uri": "test://policy",
            "content": "# Policy\n\nAudit events are retained for 365 days.",
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["chunks"] == 1
    query = client.post(
        "/v1/query",
        headers={"x-tenant-id": "acme", "x-request-id": "req_test"},
        json={"question": "How long are audit events retained?"},
    )
    assert query.status_code == 200
    assert query.headers["x-request-id"] == "req_test"
    assert query.json()["citations"][0]["id"] == "C1"
    assert "req_test" == query.json()["request_id"]

    other_tenant = client.get("/v1/documents", headers={"x-tenant-id": "other"})
    assert other_tenant.json() == []


def test_incident_commander_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "aegis_rag.api.get_settings",
        lambda: Settings(database_url=f"sqlite:///{tmp_path / 'incident.db'}"),
    )
    client = TestClient(create_app())
    client.post(
        "/v1/ingest",
        headers={"x-tenant-id": "acme"},
        json={
            "title": "Payments runbook",
            "source_uri": "runbook://payments",
            "content": (
                "# Pool exhaustion\n\nHTTP 503 and db_pool_timeout indicate "
                "PostgreSQL connection pool exhaustion. Stop the rollout first."
            ),
        },
    )
    response = client.post(
        "/v1/incidents/analyze",
        headers={"x-tenant-id": "acme", "x-request-id": "req_incident"},
        json={
            "incident_id": "INC-9001",
            "title": "Payments unavailable",
            "service": "payments-api",
            "symptoms": "All requests return HTTP 503 with db_pool_timeout",
            "telemetry": ["db.pool.wait=2500ms", "http.503.rate=100%"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["severity"] == "SEV-1"
    assert report["approval_required"] is True
    assert report["hypotheses"]
    assert report["workflow"]["engine"] == "langgraph"
    assert report["workflow"]["verification_passed"] is True
