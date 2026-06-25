from __future__ import annotations

import fnmatch
import json
import os
import shlex
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(
    os.getenv("LAB_PROJECT_ROOT", Path(__file__).resolve().parents[2])
).resolve()

TEMPLATE_DIR = Path(
    os.getenv("LAB_TEMPLATE_DIR", PROJECT_ROOT / "openclaw-training-fork")
).resolve()

LAB_DIR = Path(os.getenv("LAB_DIR", PROJECT_ROOT / ".lab")).resolve()
WORKSPACES_DIR = Path(
    os.getenv("LAB_WORKSPACES_DIR", LAB_DIR / "workspaces")
).resolve()
WORKSPACE_ID = os.getenv("LAB_WORKSPACE_ID", "default")
WORKSPACE_DIR = (WORKSPACES_DIR / WORKSPACE_ID).resolve()

RUNNER_JOBS_DIR = Path(
    os.getenv("LAB_RUNNER_JOBS_DIR", LAB_DIR / "runner-jobs")
).resolve()
RUNNER_MODE = os.getenv("LAB_RUNNER_MODE", "local").strip().lower()
CONTAINER_WORKSPACES_DIR = Path(
    os.getenv("LAB_CONTAINER_WORKSPACES_DIR", str(WORKSPACES_DIR))
)

STATE_FILE = LAB_DIR / "state.json"

CHALLENGE_MANIFEST_PATH = Path(
    os.getenv(
        "LAB_CHALLENGE_MANIFEST",
        PROJECT_ROOT / "challenge_app/challenges/cve-2026-32914-ownerless-gateway.json",
    )
).resolve()


def _load_manifest() -> dict[str, object]:
    return json.loads(CHALLENGE_MANIFEST_PATH.read_text(encoding="utf-8"))


CHALLENGE_MANIFEST = _load_manifest()
SUPPORTED_TEST_COMMANDS = (
    (
        "pnpm",
        "exec",
        "vitest",
        "run",
        "src/auto-reply/reply/commands.test.ts",
    ),
)
CHALLENGE_ID = str(CHALLENGE_MANIFEST["id"])
LAB_TITLE = str(CHALLENGE_MANIFEST["title"])
LAB_CATEGORY = str(CHALLENGE_MANIFEST["category"])
BASE_OPENCLAW_REF = str(CHALLENGE_MANIFEST["base_openclaw_ref"])
BASE_OPENCLAW_COMMIT = str(CHALLENGE_MANIFEST["base_openclaw_commit"])
TEMPLATE_SOURCE = str(CHALLENGE_MANIFEST["template_source"])
TEST_FILE_PATH = str(CHALLENGE_MANIFEST["visible_test_target"])

READABLE_SOURCE_ROOTS = tuple(CHALLENGE_MANIFEST.get("readable_source_roots", ()))
CURATED_READABLE_FILE_PATHS = tuple(CHALLENGE_MANIFEST.get("readable_paths", ()))
EXPLORER_ROOTS = tuple(CHALLENGE_MANIFEST.get("explorer_roots", READABLE_SOURCE_ROOTS))
PINNED_PATHS = tuple(CHALLENGE_MANIFEST.get("pinned_paths", CURATED_READABLE_FILE_PATHS))
ALLOWED_EXTENSIONS = tuple(str(value) for value in CHALLENGE_MANIFEST.get("allowed_extensions", (".ts", ".tsx")))
MAX_TREE_DEPTH = int(CHALLENGE_MANIFEST.get("max_tree_depth", 6))
MAX_TREE_ENTRIES = int(CHALLENGE_MANIFEST.get("max_tree_entries", 200))
EDITABLE_GLOBS = tuple(CHALLENGE_MANIFEST.get("editable_globs", ()))
READ_ONLY_GLOBS = tuple(CHALLENGE_MANIFEST.get("read_only_globs", ()))
DENIED_GLOBS = tuple(CHALLENGE_MANIFEST.get("denied_globs", ()))
TRUSTED_OVERLAY_GLOBS = tuple(CHALLENGE_MANIFEST.get("trusted_overlay_globs", ()))


def manifest_test_command(manifest: dict[str, object]) -> tuple[str, ...]:
    raw_command = manifest.get("visible_test_command")
    if isinstance(raw_command, str):
        command = tuple(shlex.split(raw_command))
    elif isinstance(raw_command, list):
        command = tuple(str(part) for part in raw_command)
    else:
        raise ValueError("visible_test_command must be a list or string")
    if command not in SUPPORTED_TEST_COMMANDS:
        raise ValueError("unsupported visible_test_command")
    return command


def _matches(patterns: tuple[object, ...], path: str) -> bool:
    for raw_pattern in patterns:
        pattern = str(raw_pattern)
        if fnmatch.fnmatchcase(path, pattern):
            return True
        if "/**/" in pattern and fnmatch.fnmatchcase(path, pattern.replace("/**/", "/")):
            return True
    return False


def _under_roots(path: str, roots: tuple[object, ...]) -> bool:
    return any(path == str(root).rstrip("/") or path.startswith(f"{str(root).rstrip('/')}/") for root in roots)


def _has_allowed_extension(path: str) -> bool:
    return PurePosixPath(path).suffix in ALLOWED_EXTENSIONS


def _depth_within_roots(path: str, roots: tuple[object, ...]) -> int | None:
    path_parts = PurePosixPath(path).parts
    for raw_root in roots:
        root = str(raw_root).rstrip("/")
        if path == root or path.startswith(f"{root}/"):
            root_parts = PurePosixPath(root).parts
            return max(0, len(path_parts) - len(root_parts))
    return None


def is_denied_path(path: str) -> bool:
    return _matches(DENIED_GLOBS, path)


def is_read_only_path(path: str) -> bool:
    return _matches(READ_ONLY_GLOBS, path)


def is_readable_path(path: str) -> bool:
    if is_denied_path(path):
        return False
    if path in CURATED_READABLE_FILE_PATHS or path in PINNED_PATHS:
        return True
    return _has_allowed_extension(path) and (
        _under_roots(path, READABLE_SOURCE_ROOTS) or _under_roots(path, EXPLORER_ROOTS)
    )


def is_explorer_root(path: str) -> bool:
    return path in tuple(str(root).rstrip("/") for root in EXPLORER_ROOTS)


def is_explorer_dir_path(path: str) -> bool:
    if is_denied_path(path):
        return False
    depth = _depth_within_roots(path, EXPLORER_ROOTS)
    return depth is not None and depth <= MAX_TREE_DEPTH


def is_editable_path(path: str) -> bool:
    return _matches(EDITABLE_GLOBS, path) and not is_read_only_path(path) and not is_denied_path(path)


def is_trusted_overlay_path(path: str) -> bool:
    return _matches(TRUSTED_OVERLAY_GLOBS, path) and is_editable_path(path)


def _discover_readable_paths() -> tuple[str, ...]:
    paths: set[str] = set(str(path) for path in CURATED_READABLE_FILE_PATHS)
    paths.update(str(path) for path in PINNED_PATHS)
    return tuple(sorted(path for path in paths if is_readable_path(path)))


def _glob_roots(patterns: tuple[object, ...]) -> tuple[str, ...]:
    roots: set[str] = set()
    for raw_pattern in patterns:
        parts: list[str] = []
        for part in PurePosixPath(str(raw_pattern)).parts:
            if any(char in part for char in "*?["):
                break
            parts.append(part)
        root = PurePosixPath(*parts) if parts else PurePosixPath(".")
        if root.suffix:
            root = root.parent
        roots.add(root.as_posix())
    return tuple(sorted(roots))


READABLE_FILE_PATHS = _discover_readable_paths()
EDITABLE_FILE_PATHS = tuple(path for path in READABLE_FILE_PATHS if is_editable_path(path))
TRUSTED_OVERLAY_ROOTS = _glob_roots(TRUSTED_OVERLAY_GLOBS)

# Backward-compatible name for code that means "writable by the participant".
ALLOWED_FILE_PATHS = EDITABLE_FILE_PATHS

TEST_COMMAND = manifest_test_command(CHALLENGE_MANIFEST)

MAX_FILE_BYTES = 1_000_000
RUN_TIMEOUT_SECONDS = int(os.getenv("LAB_RUN_TIMEOUT_SECONDS", "120"))
GATEWAY_SIM_TIMEOUT_SECONDS = int(os.getenv("LAB_GATEWAY_SIM_TIMEOUT_SECONDS", "20"))

COPY_EXCLUDED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "coverage",
    ".coverage",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".turbo",
    ".next",
    ".cache",
    ".artifacts",
    ".lab",
    ".lab-state",
}

STATUS_VULNERABLE = "Vulnerable"
STATUS_TESTS_RUNNING = "Tests Running"
STATUS_TESTS_FAILED = "Tests Failed"
STATUS_LAB_SOLVED = "Lab Solved"
