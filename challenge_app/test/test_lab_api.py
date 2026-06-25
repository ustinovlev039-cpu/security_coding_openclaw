from fastapi.testclient import TestClient

from app.hidden_validation import _trusted_overlay_paths
from app.lab_config import (
    CHALLENGE_MANIFEST,
    EDITABLE_FILE_PATHS,
    PINNED_PATHS,
    READABLE_FILE_PATHS,
    STATUS_VULNERABLE,
    TEST_COMMAND,
    TEST_FILE_PATH,
    WORKSPACE_DIR,
    manifest_test_command,
)
from app.main import app
from app.runner import GatewaySimulationResult


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
    assert TEST_FILE_PATH in body["readable_files"]
    assert "src/auto-reply/reply/commands.ts" in body["editable_files"]


def test_files_are_limited_to_allowlist():
    response = client.get("/api/lab/files")

    assert response.status_code == 200
    paths = [entry["path"] for entry in response.json()["files"]]
    assert paths == list(READABLE_FILE_PATHS)
    editable = {entry["path"]: entry["editable"] for entry in response.json()["files"]}
    assert editable[TEST_FILE_PATH] is False
    assert editable["src/auto-reply/reply/commands.ts"] is True


def test_tree_root_returns_roots_and_pinned_files_only():
    response = client.get("/api/lab/tree")

    assert response.status_code == 200
    body = response.json()
    paths = [entry["path"] for entry in body["entries"]]
    assert "src/auto-reply" in paths
    assert "src/config" in paths
    assert "src/auto-reply/reply/commands-config.ts" in paths
    assert body["pinned_paths"] == list(PINNED_PATHS)
    assert all("content" not in entry for entry in body["entries"])


def test_tree_lists_immediate_children_inside_explorer_scope():
    response = client.get("/api/lab/tree", params={"path": "src/auto-reply/reply"})

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "src/auto-reply/reply"
    entries = {entry["path"]: entry for entry in body["entries"]}
    assert entries["src/auto-reply/reply/commands-config.ts"]["editable"] is True
    assert entries["src/auto-reply/reply/commands.test.ts"]["editable"] is False


def test_tree_rejects_traversal_and_denied_roots():
    for path in (
        "../../etc",
        "src%2Fauto-reply%2F..%2F..%2F..%2Fetc",
        "node_modules",
        ".git",
        "src//config",
        "src\\config",
    ):
        response = client.get("/api/lab/tree", params={"path": path})
        assert response.status_code in {400, 403}


def test_manifest_test_command_is_trusted_and_fixed():
    assert TEST_COMMAND == tuple(CHALLENGE_MANIFEST["visible_test_command"])

    bad_manifest = {**CHALLENGE_MANIFEST, "visible_test_command": ["pnpm", "test"]}
    try:
        manifest_test_command(bad_manifest)
    except ValueError as exc:
        assert "unsupported visible_test_command" in str(exc)
    else:
        raise AssertionError("unsupported command was accepted")


def test_can_read_and_write_allowed_file():
    path = "src/auto-reply/reply/commands.ts"
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
    for path in ("package.json", "vitest.config.ts", "../package.json", "%2e%2e/package.json", "..\\package.json"):
        response = client.get(f"/api/lab/files/{path}")
        assert response.status_code in {400, 403, 404}


def test_can_read_but_not_write_visible_tests():
    read_response = client.get(f"/api/lab/files/{TEST_FILE_PATH}")
    assert read_response.status_code == 200
    assert read_response.json()["editable"] is False
    assert "handleCommands /config owner gating" in read_response.json()["content"]

    write_response = client.put(f"/api/lab/files/{TEST_FILE_PATH}", json={"content": "// nope\n"})
    assert write_response.status_code == 403


def test_rejects_writes_to_denied_paths():
    for path in (
        TEST_FILE_PATH,
        "package.json",
        "docker-compose.lab.yml",
        "vitest.config.ts",
        "challenge_app/challenges/cve-2026-32914-ownerless-gateway.json",
        "../package.json",
        "%252e%252e/package.json",
    ):
        response = client.put(f"/api/lab/files/{path}", json={"content": "// nope\n"})
        assert response.status_code in {400, 403, 404}


def test_can_read_related_config_source_file():
    response = client.get("/api/lab/files/src/config/config-paths.ts")

    assert response.status_code == 200
    assert response.json()["editable"] is True
    assert "parseConfigPath" in response.json()["content"]


def test_reset_restores_baseline_file_content():
    path = "src/auto-reply/reply/command-gates.ts"
    client.put(f"/api/lab/files/{path}", json={"content": "// overwritten\n"})

    reset = client.post("/api/lab/reset")
    assert reset.status_code == 200
    assert reset.json()["status"] == STATUS_VULNERABLE

    restored = client.get(f"/api/lab/files/{path}")
    assert restored.status_code == 200
    assert "rejectUnauthorizedCommand" in restored.json()["content"]
    assert restored.json()["content"] != "// overwritten\n"


def test_hidden_validation_overlay_uses_manifest_scope():
    client.post("/api/lab/reset")
    try:
        allowed = WORKSPACE_DIR / "src/auto-reply/reply/commands.ts"
        original = allowed.read_text(encoding="utf-8")
        allowed.write_text(f"{original}\n// overlay smoke\n", encoding="utf-8")
        (WORKSPACE_DIR / TEST_FILE_PATH).write_text("// tampered test\n", encoding="utf-8")
        (WORKSPACE_DIR / "package.json").write_text('{"tampered":true}\n', encoding="utf-8")

        paths = _trusted_overlay_paths(WORKSPACE_DIR)

        assert "src/auto-reply/reply/commands.ts" in paths
        assert TEST_FILE_PATH not in paths
        assert "package.json" not in paths
    finally:
        client.post("/api/lab/reset")


def test_gateway_simulation_schema_is_fixed(monkeypatch):
    def fake_simulation(workspace, role, command):
        return GatewaySimulationResult(
            ok=True,
            role=role,
            command=command,
            display_command="/config show",
            outcome="allowed",
            summary="ok",
            safe_output="synthetic",
            duration_ms=1,
        )

    monkeypatch.setattr("app.main.run_gateway_simulation", fake_simulation)

    ok = client.post("/api/lab/gateway-simulate", json={"role": "owner", "command": "config_show"})
    assert ok.status_code == 200
    assert ok.json()["outcome"] == "allowed"

    bad_command = client.post(
        "/api/lab/gateway-simulate",
        json={"role": "operator", "command": "rm -rf /"},
    )
    assert bad_command.status_code == 422

    extra = client.post(
        "/api/lab/gateway-simulate",
        json={"role": "operator", "command": "config_show", "shell": "id"},
    )
    assert extra.status_code == 422
