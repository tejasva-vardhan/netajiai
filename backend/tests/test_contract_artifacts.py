import json
from pathlib import Path

from backend.app.api.main import app
from backend.app.contracts.events import ComplaintLifecycleEvent


ROOT = Path(__file__).resolve().parents[2]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_committed_openapi_v1_matches_fastapi_contract():
    artifact = _load("docs/contracts/openapi-v1.json")
    generated = app.openapi()

    assert artifact == generated
    assert artifact["openapi"].startswith("3.1")
    assert all(
        path.startswith("/api/v1/")
        for path in artifact["paths"]
        if path.startswith("/api/")
    )
    assert "/api/v1/admin/complaints" in artifact["paths"]


def test_committed_lifecycle_event_schema_matches_pydantic_contract():
    artifact = _load("docs/contracts/events/complaint-lifecycle-v1.schema.json")

    assert artifact == ComplaintLifecycleEvent.model_json_schema()
    assert "complaint_id" in artifact["required"]
    assert "status" in artifact["required"]
    assert artifact["additionalProperties"] is False
