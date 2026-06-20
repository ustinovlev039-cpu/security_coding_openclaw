from __future__ import annotations

import json
import grp
import os
import pwd
import subprocess
import time
from pathlib import Path


JOBS_DIR = Path(os.getenv("RUNNER_JOBS_DIR", "/runner-jobs")).resolve()
WORKSPACES_ROOT = Path(os.getenv("RUNNER_WORKSPACES_ROOT", "/workspaces")).resolve()
ALLOWED_COMMAND = (
    "pnpm",
    "exec",
    "vitest",
    "run",
    "src/auto-reply/reply/commands.test.ts",
)
MAX_OUTPUT_CHARS = 60_000
TEST_USER = os.getenv("RUNNER_TEST_USER", "labuser")


def truncate_output(output: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    return output[-MAX_OUTPUT_CHARS:]


def safe_workspace(raw: str) -> Path:
    workspace = Path(raw).resolve()
    workspace.relative_to(WORKSPACES_ROOT)
    if not (workspace / "package.json").exists():
        raise ValueError("workspace is missing package.json")
    return workspace


def test_user_ids() -> tuple[int, int]:
    user = pwd.getpwnam(TEST_USER)
    group = grp.getgrgid(user.pw_gid)
    return user.pw_uid, group.gr_gid


def drop_to_test_user(uid: int, gid: int):
    def demote() -> None:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)

    return demote


def run_job(payload: dict[str, object]) -> dict[str, object]:
    command = tuple(str(part) for part in payload.get("command", []))
    if command != ALLOWED_COMMAND:
        raise ValueError("unsupported command")

    workspace = safe_workspace(str(payload.get("workspace", "")))
    timeout_seconds = int(payload.get("timeout_seconds", 120))
    uid, gid = test_user_ids()
    started = time.monotonic()

    try:
        completed = subprocess.run(
            ALLOWED_COMMAND,
            cwd=workspace,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": "/tmp",
                "CI": "true",
                "NO_COLOR": "1",
                "FORCE_COLOR": "0",
                "OPENCLAW_SKIP_CHANNELS": "1",
                "CLAWDBOT_SKIP_CHANNELS": "1",
            },
            preexec_fn=drop_to_test_user(uid, gid),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "output": truncate_output(completed.stdout or ""),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return {
            "ok": False,
            "exit_code": 124,
            "output": truncate_output(f"{output}\nTimed out after {timeout_seconds}s."),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


def write_result(result_path: Path, payload: dict[str, object]) -> None:
    tmp = result_path.with_suffix(".result.tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(result_path)


def process_request(request_path: Path) -> None:
    result_path = request_path.with_name(request_path.name.replace(".request.json", ".result.json"))
    result_path.unlink(missing_ok=True)
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        result = run_job(payload)
    except Exception as exc:  # noqa: BLE001 - return controlled runner errors to backend
        result = {
            "ok": False,
            "exit_code": 1,
            "output": f"Runner rejected job: {exc}",
            "duration_ms": 0,
        }
    write_result(result_path, result)
    request_path.unlink(missing_ok=True)


def main() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(JOBS_DIR, 0o700)
    while True:
        requests = sorted(JOBS_DIR.glob("*.request.json"))
        if not requests:
            time.sleep(0.2)
            continue
        for request_path in requests:
            process_request(request_path)


if __name__ == "__main__":
    main()
