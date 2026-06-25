from __future__ import annotations

import json
import os
import posixpath
import shutil
from urllib.parse import unquote
from pathlib import Path

from fastapi import HTTPException, status

from app.lab_config import (
    ALLOWED_EXTENSIONS,
    COPY_EXCLUDED_NAMES,
    EXPLORER_ROOTS,
    LAB_DIR,
    MAX_TREE_ENTRIES,
    MAX_FILE_BYTES,
    PINNED_PATHS,
    READABLE_FILE_PATHS,
    STATE_FILE,
    STATUS_LAB_SOLVED,
    STATUS_VULNERABLE,
    TEMPLATE_DIR,
    WORKSPACE_DIR,
    is_editable_path,
    is_explorer_dir_path,
    is_explorer_root,
    is_readable_path,
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


TREE_DENIED_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".lab",
    ".lab-state",
    ".cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "coverage",
    "__pycache__",
}

PACKAGE_METADATA_NAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "yarn.lock",
}


def _normalize_path(raw_path: str, *, allow_basename_alias: bool = True) -> str:
    cleaned = raw_path.strip()
    for _ in range(3):
        decoded = unquote(cleaned)
        if decoded == cleaned:
            break
        cleaned = decoded
    if "\x00" in cleaned or "\\" in cleaned or "//" in cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    if cleaned.startswith("/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    normalized = posixpath.normpath(cleaned)
    if normalized == "." or normalized.startswith("../") or normalized == "..":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    if normalized.startswith("/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    if allow_basename_alias and "/" not in normalized:
        matches = [file_path for file_path in READABLE_FILE_PATHS if Path(file_path).name == normalized]
        if len(matches) == 1:
            normalized = matches[0]
    return normalized


def normalize_readable_path(raw_path: str) -> str:
    normalized = _normalize_path(raw_path)
    if not is_readable_path(normalized):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="File is not readable")
    return normalized


def normalize_editable_path(raw_path: str) -> str:
    normalized = _normalize_path(raw_path)
    if not is_editable_path(normalized):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="File is not editable")
    return normalized


def _ensure_inside_workspace(path: Path, workspace: Path) -> None:
    if not path.resolve().is_relative_to(workspace.resolve()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")


def _language_for(path: str) -> str:
    suffix = Path(path).suffix
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix == ".json":
        return "json"
    return "text"


def _is_allowed_source_file(path: str) -> bool:
    return Path(path).suffix in ALLOWED_EXTENSIONS and is_readable_path(path)


def _tree_entry(path: str, entry_type: str, *, pinned: bool = False) -> dict[str, object]:
    editable = entry_type == "file" and is_editable_path(path)
    return {
        "path": path,
        "name": Path(path).name,
        "type": entry_type,
        "language": _language_for(path) if entry_type == "file" else None,
        "editable": editable,
        "read_only": not editable,
        "pinned": pinned,
        "expandable": entry_type == "directory",
    }


def _has_denied_tree_part(path: str) -> bool:
    parts = Path(path).parts
    return any(part in TREE_DENIED_NAMES for part in parts)


def _is_tree_denied(path: str) -> bool:
    name = Path(path).name
    return (
        _has_denied_tree_part(path)
        or name in PACKAGE_METADATA_NAMES
        or name.startswith("Dockerfile")
        or name.startswith("docker-compose")
    )


def _resolve_workspace_child(workspace: Path, relative_path: str) -> Path:
    candidate = (workspace / relative_path).resolve()
    _ensure_inside_workspace(candidate, workspace)
    return candidate


def _normalize_tree_dir_path(raw_path: str | None) -> str:
    if raw_path is None or raw_path.strip() == "":
        return ""
    normalized = _normalize_path(raw_path, allow_basename_alias=False)
    if _is_tree_denied(normalized) or not is_explorer_dir_path(normalized):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Directory is not explorable")
    return normalized


def list_source_tree(raw_path: str | None = None) -> dict[str, object]:
    workspace = ensure_workspace()
    normalized = _normalize_tree_dir_path(raw_path)
    roots = [str(root).rstrip("/") for root in EXPLORER_ROOTS]
    pinned_paths = [str(path) for path in PINNED_PATHS if is_readable_path(str(path))]

    if normalized == "":
        entries: list[dict[str, object]] = []
        seen: set[str] = set()
        for root in roots:
            if root in seen or _is_tree_denied(root) or not is_explorer_root(root):
                continue
            root_path = _resolve_workspace_child(workspace, root)
            if root_path.exists() and root_path.is_dir():
                entries.append(_tree_entry(root, "directory"))
                seen.add(root)
        for pinned_path in pinned_paths:
            if pinned_path in seen or _is_tree_denied(pinned_path):
                continue
            file_path = _resolve_workspace_child(workspace, pinned_path)
            if file_path.exists() and file_path.is_file():
                entries.append(_tree_entry(pinned_path, "file", pinned=True))
                seen.add(pinned_path)
            if len(entries) >= MAX_TREE_ENTRIES:
                break
        return {
            "path": "",
            "entries": entries,
            "roots": roots,
            "pinned_paths": pinned_paths,
            "max_entries": MAX_TREE_ENTRIES,
        }

    directory = _resolve_workspace_child(workspace, normalized)
    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Directory not found")
    if directory.is_symlink():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")

    entries = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        relative_path = child.relative_to(workspace).as_posix()
        if _is_tree_denied(relative_path):
            continue
        try:
            _ensure_inside_workspace(child.resolve(), workspace)
        except HTTPException:
            continue
        if child.is_symlink():
            continue
        if child.is_dir():
            if is_explorer_dir_path(relative_path):
                entries.append(_tree_entry(relative_path, "directory"))
        elif child.is_file() and _is_allowed_source_file(relative_path):
            entries.append(_tree_entry(relative_path, "file", pinned=relative_path in pinned_paths))
        if len(entries) >= MAX_TREE_ENTRIES:
            break

    return {
        "path": normalized,
        "entries": entries,
        "roots": roots,
        "pinned_paths": pinned_paths,
        "max_entries": MAX_TREE_ENTRIES,
    }


def _deny_bad_write_target(path: Path, workspace: Path) -> None:
    _ensure_inside_workspace(path.parent, workspace)
    if path.is_symlink():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    if path.exists():
        _ensure_inside_workspace(path, workspace)


def is_editable_file(raw_path: str) -> bool:
    try:
        return is_editable_path(_normalize_path(raw_path))
    except HTTPException:
        return False


def resolve_readable_file(raw_path: str) -> Path:
    workspace = ensure_workspace()
    normalized = normalize_readable_path(raw_path)
    resolved = (workspace / normalized).resolve()
    _ensure_inside_workspace(resolved, workspace)
    return resolved


def list_allowed_files() -> list[dict[str, object]]:
    ensure_workspace()
    return [
        {
            "path": file_path,
            "name": Path(file_path).name,
            "language": _language_for(file_path),
            "editable": is_editable_path(file_path),
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
    path = workspace / normalized
    _deny_bad_write_target(path, workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    set_status(STATUS_VULNERABLE, last_test=None)
    return normalized
