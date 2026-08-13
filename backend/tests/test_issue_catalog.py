from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.config import Settings
from backend.app.domain.issue_catalog import ISSUE_CATALOG_VERSION, ISSUE_CATEGORIES


def test_complaint_category_catalog_is_versioned_and_server_owned():
    client = TestClient(create_app(Settings(environment="test")))

    response = client.get("/api/v1/complaints/categories")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == ISSUE_CATALOG_VERSION
    assert [item["code"] for item in payload["items"]] == [
        category.code for category in ISSUE_CATEGORIES
    ]
    assert payload["items"][0]["icon"] == "🛣️"
    assert set(payload["items"][0]) == {
        "code",
        "icon",
        "label_hi",
        "label_en",
        "spoken_hi",
    }
