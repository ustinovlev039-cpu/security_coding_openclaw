from __future__ import annotations

import os
from pathlib import Path


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

EDITABLE_FILE_PATHS = (
    "src/auto-reply/reply/commands-config.ts",
    "src/auto-reply/reply/command-gates.ts",
)

TEST_FILE_PATH = "src/auto-reply/reply/commands.test.ts"

READABLE_FILE_PATHS = (
    *EDITABLE_FILE_PATHS,
    TEST_FILE_PATH,
)

# Backward-compatible name for code that means "writable by the participant".
ALLOWED_FILE_PATHS = EDITABLE_FILE_PATHS

TEST_COMMAND = (
    "pnpm",
    "exec",
    "vitest",
    "run",
    "src/auto-reply/reply/commands.test.ts",
)

MAX_FILE_BYTES = 1_000_000
RUN_TIMEOUT_SECONDS = int(os.getenv("LAB_RUN_TIMEOUT_SECONDS", "120"))

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
