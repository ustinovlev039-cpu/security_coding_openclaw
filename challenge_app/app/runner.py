from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.lab_config import (
    CONTAINER_WORKSPACES_DIR,
    GATEWAY_SIM_TIMEOUT_SECONDS,
    LAB_DIR,
    RUN_TIMEOUT_SECONDS,
    RUNNER_JOBS_DIR,
    RUNNER_MODE,
    TEST_COMMAND,
    WORKSPACES_DIR,
)


MAX_OUTPUT_CHARS = 60_000
MAX_SIMULATION_OUTPUT_CHARS = 2_000
SIMULATION_COMMANDS = {
    "config_show": "/config show",
    "debug_show": "/debug show",
}


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    exit_code: int
    command: tuple[str, ...]
    output: str
    duration_ms: int

    def to_summary(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "command": " ".join(self.command),
            "output": self.output,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class GatewaySimulationResult:
    ok: bool
    role: str
    command: str
    display_command: str
    outcome: str
    summary: str
    safe_output: str
    duration_ms: int

    def to_response(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "role": self.role,
            "command": self.command,
            "display_command": self.display_command,
            "outcome": self.outcome,
            "summary": self.summary,
            "safe_output": self.safe_output,
            "duration_ms": self.duration_ms,
        }


def _truncate_output(output: str) -> str:
    if len(output) <= MAX_OUTPUT_CHARS:
        return output
    return output[-MAX_OUTPUT_CHARS:]


def _runner_env() -> dict[str, str]:
    home = LAB_DIR / "runner-home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "CI": "true",
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
        "OPENCLAW_SKIP_CHANNELS": "1",
        "CLAWDBOT_SKIP_CHANNELS": "1",
    }


def _run_local(workspace_dir: Path, timeout_seconds: int) -> CommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            TEST_COMMAND,
            cwd=workspace_dir,
            env=_runner_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        output = _truncate_output(completed.stdout or "")
        return CommandResult(
            ok=completed.returncode == 0,
            exit_code=completed.returncode,
            command=TEST_COMMAND,
            output=output,
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return CommandResult(
            ok=False,
            exit_code=124,
            command=TEST_COMMAND,
            output=_truncate_output(f"{output}\nTimed out after {timeout_seconds}s."),
            duration_ms=duration_ms,
        )


def _workspace_path_for_file_runner(workspace_dir: Path) -> str:
    rel = workspace_dir.resolve().relative_to(WORKSPACES_DIR.resolve())
    return str(CONTAINER_WORKSPACES_DIR / rel)


def _submit_file_runner_job(
    workspace_dir: Path,
    payload: dict[str, object],
    timeout_seconds: int,
) -> dict[str, object]:
    RUNNER_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    request_path = RUNNER_JOBS_DIR / f"{job_id}.request.json"
    result_path = RUNNER_JOBS_DIR / f"{job_id}.result.json"
    tmp_path = RUNNER_JOBS_DIR / f"{job_id}.request.tmp"

    request_payload = {
        "id": job_id,
        "workspace": _workspace_path_for_file_runner(workspace_dir),
        "timeout_seconds": timeout_seconds,
        **payload,
    }
    tmp_path.write_text(json.dumps(request_payload), encoding="utf-8")
    tmp_path.replace(request_path)

    started = time.monotonic()
    deadline = started + timeout_seconds + 15
    while time.monotonic() < deadline:
        if result_path.exists():
            duration_ms = int((time.monotonic() - started) * 1000)
            raw = json.loads(result_path.read_text(encoding="utf-8"))
            result_path.unlink(missing_ok=True)
            request_path.unlink(missing_ok=True)
            raw.setdefault("duration_ms", duration_ms)
            return raw
        time.sleep(0.2)

    request_path.unlink(missing_ok=True)
    return {
        "ok": False,
        "exit_code": 124,
        "output": f"Runner timed out after {timeout_seconds}s.",
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def _run_via_file_runner(workspace_dir: Path, timeout_seconds: int) -> CommandResult:
    raw = _submit_file_runner_job(
        workspace_dir,
        {"job_type": "tests"},
        timeout_seconds,
    )
    return CommandResult(
        ok=bool(raw.get("ok")),
        exit_code=int(raw.get("exit_code", 1)),
        command=TEST_COMMAND,
        output=_truncate_output(str(raw.get("output", ""))),
        duration_ms=int(raw.get("duration_ms", 0)),
    )


def run_fixed_tests(workspace_dir: Path, timeout_seconds: int = RUN_TIMEOUT_SECONDS) -> CommandResult:
    if tuple(TEST_COMMAND) != TEST_COMMAND:
        raise RuntimeError("Unexpected test command configuration")
    if RUNNER_MODE == "file":
        return _run_via_file_runner(workspace_dir, timeout_seconds)
    return _run_local(workspace_dir, timeout_seconds)


def _error_simulation(role: str, command: str, summary: str) -> GatewaySimulationResult:
    return GatewaySimulationResult(
        ok=False,
        role=role,
        command=command,
        display_command=SIMULATION_COMMANDS.get(command, command),
        outcome="error",
        summary=summary,
        safe_output="Simulation did not complete.",
        duration_ms=0,
    )


def _run_gateway_simulation_via_file_runner(
    workspace_dir: Path,
    role: str,
    command: str,
    timeout_seconds: int,
) -> GatewaySimulationResult:
    raw = _submit_file_runner_job(
        workspace_dir,
        {
            "job_type": "gateway_simulation",
            "role": role,
            "command_id": command,
        },
        timeout_seconds,
    )
    return GatewaySimulationResult(
        ok=bool(raw.get("ok")),
        role=role,
        command=command,
        display_command=str(raw.get("display_command", SIMULATION_COMMANDS.get(command, command))),
        outcome=str(raw.get("outcome", "error")),
        summary=str(raw.get("summary", "Gateway simulation failed."))[:500],
        safe_output=str(raw.get("safe_output", ""))[:MAX_SIMULATION_OUTPUT_CHARS],
        duration_ms=int(raw.get("duration_ms", 0)),
    )


def run_gateway_simulation(
    workspace_dir: Path,
    role: str,
    command: str,
    timeout_seconds: int = GATEWAY_SIM_TIMEOUT_SECONDS,
) -> GatewaySimulationResult:
    if role not in {"owner", "operator"} or command not in SIMULATION_COMMANDS:
        return _error_simulation(role, command, "Unsupported gateway simulation request.")
    if RUNNER_MODE != "file":
        return _error_simulation(role, command, "Gateway simulation requires the isolated file runner.")
    return _run_gateway_simulation_via_file_runner(workspace_dir, role, command, timeout_seconds)
