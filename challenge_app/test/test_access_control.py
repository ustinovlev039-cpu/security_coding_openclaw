from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

def test_owner_can_read_config():
    response = client.get("/config", headers=auth("owner-token"))

    assert response.status_code == 200
    assert response.json()["actor"] == "training_owner"

def test_owner_can_read_debug():
    response = client.get("/debug", headers=auth("owner-token"))

    assert response.status_code == 200
    assert response.json()["actor"] == "training_owner"


def test_operator_cannot_read_config():
    response = client.get("/config", headers=auth("operator-token"))

    assert response.status_code == 403


def test_operator_cannot_read_debug():
    response = client.get("/debug", headers=auth("operator-token"))

    assert response.status_code == 403


def test_operator_can_still_use_normal_command_status():
    response = client.get("/commands/status", headers=auth("operator-token"))

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["actor"] == "training_operator"


def test_operator_can_still_use_normal_command_ping():
    response = client.post("/commands/ping", headers=auth("operator-token"))

    assert response.status_code == 200
    assert response.json()["pong"] is True
    assert response.json()["actor"] == "training_operator"


def test_viewer_cannot_use_commands():
    response = client.get("/commands/status", headers=auth("viewer-token"))

    assert response.status_code == 403