from fastapi.testclient import TestClient

from app.main import app


def test_root_returns_service_metadata() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "HelpFlow API"
