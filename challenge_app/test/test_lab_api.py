from fastapi.testclient import TestClient

from app.lab_config import EDITABLE_FILE_PATHS, READABLE_FILE_PATHS, STATUS_VULNERABLE, TEST_FILE_PATH
from app.main import app


client = TestClient(app)


def test_status_initializes_workspace():
    response = client.get("/api/lab/status")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "OpenClaw: Ownerless Gateway"
    assert body["category"] == "Broken Access Control / Security Coding"
    assert body["status"] == STATUS_VULNERABLE
    assert body["allowed_files"] == list(EDITABLE_FILE_PATHS)
    assert body["editable_files"] == list(EDITABLE_FILE_PATHS)
    assert body["readable_files"] == list(READABLE_FILE_PATHS)


def test_files_are_limited_to_allowlist():
    response = client.get("/api/lab/files")

    assert response.status_code == 200
    paths = [entry["path"] for entry in response.json()["files"]]
    assert paths == list(READABLE_FILE_PATHS)
    editable = {entry["path"]: entry["editable"] for entry in response.json()["files"]}
    assert editable[TEST_FILE_PATH] is False


def test_can_read_and_write_allowed_file():
    path = EDITABLE_FILE_PATHS[1]
    original = client.get(f"/api/lab/files/{path}")
    assert original.status_code == 200

    updated = original.json()["content"] + "\n// lab api smoke\n"
    write = client.put(f"/api/lab/files/{path}", json={"content": updated})
    assert write.status_code == 200
    assert write.json()["saved"] is True

    read_back = client.get(f"/api/lab/files/{path}")
    assert read_back.status_code == 200
    assert read_back.json()["content"].endswith("// lab api smoke\n")


def test_rejects_files_outside_allowlist():
    response = client.get("/api/lab/files/package.json")

    assert response.status_code == 403


def test_can_read_but_not_write_visible_tests():
    read_response = client.get(f"/api/lab/files/{TEST_FILE_PATH}")
    assert read_response.status_code == 200
    assert read_response.json()["editable"] is False
    assert "handleCommands /config owner gating" in read_response.json()["content"]

    write_response = client.put(f"/api/lab/files/{TEST_FILE_PATH}", json={"content": "// nope\n"})
    assert write_response.status_code == 403


def test_reset_restores_baseline_file_content():
    path = EDITABLE_FILE_PATHS[1]
    client.put(f"/api/lab/files/{path}", json={"content": "// overwritten\n"})

    reset = client.post("/api/lab/reset")
    assert reset.status_code == 200
    assert reset.json()["status"] == STATUS_VULNERABLE

    restored = client.get(f"/api/lab/files/{path}")
    assert restored.status_code == 200
    assert "rejectUnauthorizedCommand" in restored.json()["content"]
    assert restored.json()["content"] != "// overwritten\n"
