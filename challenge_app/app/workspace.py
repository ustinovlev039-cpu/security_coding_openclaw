from __future__ import annotations

import json
import os
import posixpath
import shutil
from pathlib import Path

from fastapi import HTTPException, status

from app.lab_config import (
    COPY_EXCLUDED_NAMES,
    EDITABLE_FILE_PATHS,
    LAB_DIR,
    MAX_FILE_BYTES,
    READABLE_FILE_PATHS,
    STATE_FILE,
    STATUS_LAB_SOLVED,
    STATUS_VULNERABLE,
    TEMPLATE_DIR,
    WORKSPACE_DIR,
)


def _default_state() -> dict[str, object]:
    return {
        "status": STATUS_VULNERABLE,
        "last_test": None,
        "solved": False,
    }


def _copy_ignore(_: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in COPY_EXCLUDED_NAMES:
            ignored.add(name)
        elif name.endswith((".pyc", ".pyo")):
            ignored.add(name)
    return ignored


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_state() -> dict[str, object]:
    if not STATE_FILE.exists():
        return _default_state()
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_state()
    if not isinstance(state, dict):
        return _default_state()
    return {**_default_state(), **state}


def write_state(state: dict[str, object]) -> None:
    _atomic_write_json(STATE_FILE, {**_default_state(), **state})


def set_status(status_value: str, **extra: object) -> None:
    current = read_state()
    solved = status_value == STATUS_LAB_SOLVED
    write_state({**current, **extra, "status": status_value, "solved": solved})


def _dependency_target() -> Path | None:
    configured = os.getenv("LAB_NODE_MODULES_TARGET")
    if configured:
        return Path(configured)

    target = TEMPLATE_DIR / "node_modules"
    return target.resolve() if target.exists() else None


def link_dependency_artifacts(workspace_dir: Path) -> None:
    if os.getenv("LAB_LINK_NODE_MODULES", "true").strip().lower() in {"0", "false", "no"}:
        return

    target = _dependency_target()
    if target is None:
        return

    destination = workspace_dir / "node_modules"
    if destination.exists() or destination.is_symlink():
        return
    destination.symlink_to(target, target_is_directory=True)


def reset_workspace() -> Path:
    if not (TEMPLATE_DIR / "package.json").exists():
        raise RuntimeError(f"OpenClaw template not found at {TEMPLATE_DIR}")

    LAB_DIR.mkdir(parents=True, exist_ok=True)
    if WORKSPACE_DIR.exists() or WORKSPACE_DIR.is_symlink():
        shutil.rmtree(WORKSPACE_DIR)

    shutil.copytree(TEMPLATE_DIR, WORKSPACE_DIR, ignore=_copy_ignore)
    link_dependency_artifacts(WORKSPACE_DIR)
    write_state(_default_state())
    return WORKSPACE_DIR


def ensure_workspace() -> Path:
    if not (WORKSPACE_DIR / "package.json").exists():
        return reset_workspace()
    link_dependency_artifacts(WORKSPACE_DIR)
    return WORKSPACE_DIR


def _normalize_path(raw_path: str, allowed_paths: tuple[str, ...], denied_detail: str) -> str:
    cleaned = raw_path.strip().replace("\\", "/")
    normalized = posixpath.normpath(cleaned)
    if normalized == "." or normalized.startswith("../") or normalized == "..":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    if normalized.startswith("/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    if "/" not in normalized:
        matches = [file_path for file_path in READABLE_FILE_PATHS if Path(file_path).name == normalized]
        if len(matches) == 1:
            normalized = matches[0]
    if normalized not in allowed_paths:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=denied_detail)
    return normalized


def normalize_readable_path(raw_path: str) -> str:
    return _normalize_path(raw_path, READABLE_FILE_PATHS, "File is not readable")


def normalize_editable_path(raw_path: str) -> str:
    return _normalize_path(raw_path, EDITABLE_FILE_PATHS, "File is not editable")


def is_editable_file(raw_path: str) -> bool:
    cleaned = raw_path.strip().replace("\\", "/")
    normalized = posixpath.normpath(cleaned)
    return normalized in EDITABLE_FILE_PATHS


def resolve_readable_file(raw_path: str) -> Path:
    workspace = ensure_workspace()
    normalized = normalize_readable_path(raw_path)
    resolved = (workspace / normalized).resolve()
    if not resolved.is_relative_to(workspace.resolve()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    return resolved


def list_allowed_files() -> list[dict[str, object]]:
    ensure_workspace()
    return [
        {
            "path": file_path,
            "name": Path(file_path).name,
            "language": "typescript",
            "editable": file_path in EDITABLE_FILE_PATHS,
        }
        for file_path in READABLE_FILE_PATHS
    ]


def read_allowed_file(raw_path: str) -> str:
    path = resolve_readable_file(raw_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
    return path.read_text(encoding="utf-8")


def write_allowed_file(raw_path: str, content: str) -> str:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")
    normalized = normalize_editable_path(raw_path)
    workspace = ensure_workspace()
    path = (workspace / normalized).resolve()
    if not path.is_relative_to(workspace.resolve()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    set_status(STATUS_VULNERABLE, last_test=None)
    return normalized
