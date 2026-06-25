from __future__ import annotations

import json
import grp
import os
import pwd
import select
import signal
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


JOBS_DIR = Path(os.getenv("RUNNER_JOBS_DIR", "/runner-jobs")).resolve()
WORKSPACES_ROOT = Path(os.getenv("RUNNER_WORKSPACES_ROOT", "/workspaces")).resolve()
RUNTIME_ROOT = Path(os.getenv("RUNNER_RUNTIME_ROOT", "/tmp")).resolve()
NODE_MODULES_SOURCE = Path(
    os.getenv("RUNNER_NODE_MODULES_SOURCE", "/deps/project/node_modules")
).resolve()
ALLOWED_COMMAND = (
    "pnpm",
    "exec",
    "vitest",
    "run",
    "src/auto-reply/reply/commands.test.ts",
)
MAX_OUTPUT_CHARS = 60_000
MAX_SIMULATION_OUTPUT_BYTES = 80_000
SIMULATION_SAFE_OUTPUT_CHARS = 2_000
SIMULATION_TIMEOUT_SECONDS = 20
SIMULATION_RESULT_PREFIX = "__OPENCLAW_GATEWAY_SIMULATION_RESULT__"
TEST_USER = os.getenv("RUNNER_TEST_USER", "labuser")
RUNTIME_NODE_MODULES_WRITABLE = {".vite", ".vite-temp"}
SIMULATION_DRIVER = Path("/runner/gateway-simulation-driver.ts")
SIMULATION_COMMANDS = {
    "config_show": "/config show",
    "debug_show": "/debug show",
}
SIMULATION_ROLES = {"owner", "operator"}


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


def start_process_group_as_test_user(uid: int, gid: int):
    def demote() -> None:
        os.setsid()
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)

    return demote


def kill_process_group(pid: int, uid: int | None = None, gid: int | None = None) -> None:
    try:
        if uid is None or gid is None:
            os.killpg(pid, signal.SIGKILL)
        else:
            with effective_user(uid, gid):
                os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@contextmanager
def effective_user(uid: int, gid: int):
    os.setegid(gid)
    os.seteuid(uid)
    try:
        yield
    finally:
        os.seteuid(0)
        os.setegid(0)


def chmod_dir(path: Path, mode: int = 0o700) -> None:
    os.chmod(path, mode)


def link_workspace(source: Path, destination: Path) -> None:
    destination.mkdir()
    for child in source.iterdir():
        if child.name == "node_modules":
            continue
        (destination / child.name).symlink_to(child, target_is_directory=child.is_dir())


def link_node_modules(destination: Path) -> None:
    if not NODE_MODULES_SOURCE.is_dir():
        raise ValueError("dependency layer is missing node_modules")

    node_modules = destination / "node_modules"
    node_modules.mkdir()
    for child in NODE_MODULES_SOURCE.iterdir():
        if child.name in RUNTIME_NODE_MODULES_WRITABLE:
            continue
        (node_modules / child.name).symlink_to(child, target_is_directory=child.is_dir())
    for name in RUNTIME_NODE_MODULES_WRITABLE:
        (node_modules / name).mkdir()


def prepare_runtime_workspace(workspace: Path) -> tuple[Path, Path]:
    job_root = RUNTIME_ROOT / f"job-{uuid.uuid4().hex}"
    runtime_workspace = job_root / "workspace"
    job_home = job_root / "home"
    job_tmp = job_root / "tmp"

    try:
        job_root.mkdir(mode=0o700)
        link_workspace(workspace, runtime_workspace)
        link_node_modules(runtime_workspace)
        job_home.mkdir()
        job_tmp.mkdir()

        for path in (
            job_root,
            runtime_workspace,
            runtime_workspace / "node_modules",
            runtime_workspace / "node_modules" / ".vite",
            runtime_workspace / "node_modules" / ".vite-temp",
            job_home,
            job_tmp,
        ):
            chmod_dir(path)

        return runtime_workspace, job_root
    except Exception:
        shutil.rmtree(job_root, ignore_errors=True)
        raise


def run_job(payload: dict[str, object]) -> dict[str, object]:
    if "command" in payload:
        raise ValueError("command strings are not accepted")

    job_type = str(payload.get("job_type", ""))
    if job_type == "tests":
        return run_tests_job(payload)
    if job_type == "gateway_simulation":
        return run_gateway_simulation_job(payload)
    raise ValueError("unsupported job type")


def run_tests_job(payload: dict[str, object]) -> dict[str, object]:
    workspace = safe_workspace(str(payload.get("workspace", "")))
    timeout_seconds = int(payload.get("timeout_seconds", 120))
    uid, gid = test_user_ids()
    started = time.monotonic()
    job_root: Path | None = None

    try:
        with effective_user(uid, gid):
            runtime_workspace, job_root = prepare_runtime_workspace(workspace)
        runtime_command = (
            "pnpm",
            "--dir",
            str(runtime_workspace),
            "exec",
            "vitest",
            "run",
            "src/auto-reply/reply/commands.test.ts",
        )
        completed = subprocess.run(
            runtime_command,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(job_root / "home"),
                "TMPDIR": str(job_root / "tmp"),
                "XDG_CACHE_HOME": str(job_root / "home" / ".cache"),
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
    finally:
        if job_root is not None:
            with effective_user(uid, gid):
                shutil.rmtree(job_root, ignore_errors=True)


def run_limited_process(
    runtime_command: tuple[str, ...],
    env: dict[str, str],
    timeout_seconds: int,
    uid: int,
    gid: int,
    max_output_bytes: int,
) -> tuple[int, str, int, bool]:
    started = time.monotonic()
    deadline = started + timeout_seconds
    buffer = bytearray()
    truncated = False
    process = subprocess.Popen(
        runtime_command,
        env=env,
        preexec_fn=start_process_group_as_test_user(uid, gid),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    assert process.stdout is not None
    fd = process.stdout.fileno()
    timed_out = False

    def append(data: bytes) -> None:
        nonlocal truncated
        buffer.extend(data)
        if len(buffer) > max_output_bytes:
            del buffer[: len(buffer) - max_output_bytes]
            truncated = True

    try:
        while True:
            if time.monotonic() > deadline:
                timed_out = True
                kill_process_group(process.pid, uid, gid)
                break
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                chunk = os.read(fd, 4096)
                if chunk:
                    append(chunk)
            if process.poll() is not None:
                while True:
                    ready, _, _ = select.select([fd], [], [], 0)
                    if not ready:
                        break
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    append(chunk)
                break
    finally:
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            kill_process_group(process.pid, uid, gid)
            process.wait(timeout=2)

    output = buffer.decode("utf-8", errors="replace")
    if truncated:
        output = "[output truncated]\n" + output
    if timed_out:
        output = f"{output}\nTimed out after {timeout_seconds}s."
        return 124, output, int((time.monotonic() - started) * 1000), True
    return process.returncode or 0, output, int((time.monotonic() - started) * 1000), truncated


def safe_simulation_payload(
    role: str,
    command: str,
    outcome: str,
    ok: bool,
    summary: str,
    safe_output: str,
    duration_ms: int,
) -> dict[str, object]:
    if outcome not in {"allowed", "blocked", "error"}:
        outcome = "error"
        ok = False
        summary = "Gateway simulation returned an unsupported outcome."
        safe_output = "Unsupported simulation result."
    return {
        "ok": ok,
        "role": role,
        "command": command,
        "display_command": SIMULATION_COMMANDS.get(command, command),
        "outcome": outcome,
        "summary": summary[:500],
        "safe_output": safe_output[:SIMULATION_SAFE_OUTPUT_CHARS],
        "duration_ms": duration_ms,
    }


def parse_simulation_result(output: str, role: str, command: str, duration_ms: int) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        if not line.startswith(SIMULATION_RESULT_PREFIX):
            continue
        raw = json.loads(line[len(SIMULATION_RESULT_PREFIX) :])
        if raw.get("role") != role or raw.get("command") != command:
            raise ValueError("simulation result did not match request")
        return safe_simulation_payload(
            role=role,
            command=command,
            outcome=str(raw.get("outcome", "error")),
            ok=bool(raw.get("ok")),
            summary=str(raw.get("summary", "")),
            safe_output=str(raw.get("safe_output", "")),
            duration_ms=duration_ms,
        )
    return safe_simulation_payload(
        role=role,
        command=command,
        outcome="error",
        ok=False,
        summary="Gateway simulation did not return a structured result.",
        safe_output="No structured simulation result was produced.",
        duration_ms=duration_ms,
    )


def run_gateway_simulation_job(payload: dict[str, object]) -> dict[str, object]:
    workspace = safe_workspace(str(payload.get("workspace", "")))
    role = str(payload.get("role", ""))
    command = str(payload.get("command_id", ""))
    if role not in SIMULATION_ROLES:
        raise ValueError("unsupported simulation role")
    if command not in SIMULATION_COMMANDS:
        raise ValueError("unsupported simulation command")

    timeout_seconds = min(int(payload.get("timeout_seconds", SIMULATION_TIMEOUT_SECONDS)), 30)
    uid, gid = test_user_ids()
    job_root: Path | None = None

    try:
        with effective_user(uid, gid):
            runtime_workspace, job_root = prepare_runtime_workspace(workspace)
        runtime_command = (
            "pnpm",
            "--dir",
            str(runtime_workspace),
            "exec",
            "tsx",
            str(SIMULATION_DRIVER),
            role,
            command,
        )
        exit_code, output, duration_ms, _ = run_limited_process(
            runtime_command,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(job_root / "home"),
                "TMPDIR": str(job_root / "tmp"),
                "XDG_CACHE_HOME": str(job_root / "home" / ".cache"),
                "CI": "true",
                "NO_COLOR": "1",
                "FORCE_COLOR": "0",
                "OPENCLAW_SKIP_CHANNELS": "1",
                "CLAWDBOT_SKIP_CHANNELS": "1",
                "OPENCLAW_SIM_WORKSPACE": str(runtime_workspace),
            },
            timeout_seconds=timeout_seconds,
            uid=uid,
            gid=gid,
            max_output_bytes=MAX_SIMULATION_OUTPUT_BYTES,
        )
        if exit_code == 124:
            return safe_simulation_payload(
                role=role,
                command=command,
                outcome="error",
                ok=False,
                summary="Gateway simulation timed out.",
                safe_output="Simulation timed out.",
                duration_ms=duration_ms,
            )
        return parse_simulation_result(output, role, command, duration_ms)
    finally:
        if job_root is not None:
            with effective_user(uid, gid):
                shutil.rmtree(job_root, ignore_errors=True)


def matching_proc_cmdlines(marker: str) -> list[str]:
    matches: list[str] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return matches
    for candidate in proc.iterdir():
        if not candidate.name.isdigit():
            continue
        try:
            raw = (candidate / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8",
                errors="replace",
            )
        except OSError:
            continue
        if marker in raw:
            matches.append(raw)
    return matches


def timeout_cleanup_self_check() -> dict[str, object]:
    uid, gid = test_user_ids()
    marker = f"openclaw-timeout-child-{uuid.uuid4().hex}"
    exit_code, _, _, _ = run_limited_process(
        (
            "python3",
            "-c",
            "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import sys,time; time.sleep(30)',sys.argv[1]]); time.sleep(30)",
            marker,
        ),
        env={"PATH": os.environ.get("PATH", "")},
        timeout_seconds=1,
        uid=uid,
        gid=gid,
        max_output_bytes=10_000,
    )
    time.sleep(0.5)
    leaked = matching_proc_cmdlines(marker)

    before = {path.name for path in RUNTIME_ROOT.glob("job-*")}
    workspace = os.getenv("RUNNER_SELF_CHECK_WORKSPACE", str(WORKSPACES_ROOT / "default"))
    result = run_gateway_simulation_job(
        {
            "workspace": workspace,
            "role": "owner",
            "command_id": "debug_show",
            "timeout_seconds": 0,
        }
    )
    after = {path.name for path in RUNTIME_ROOT.glob("job-*")}
    runtime_removed = before == after
    ok = exit_code == 124 and result.get("outcome") == "error" and runtime_removed and not leaked
    return {
        "ok": ok,
        "timeout_exit_code": exit_code,
        "simulation_outcome": result.get("outcome"),
        "runtime_removed": runtime_removed,
        "leaked_processes": leaked,
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
    if os.getenv("RUNNER_SELF_CHECK") == "timeout_cleanup":
        result = timeout_cleanup_self_check()
        print(json.dumps(result))
        raise SystemExit(0 if result["ok"] else 1)

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
