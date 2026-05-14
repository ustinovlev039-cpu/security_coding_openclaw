from fastapi import Depends, FastAPI
from pydantic import BaseModel

from app.auth import User, get_current_user
from app.permissions import require_command_access, require_owner
from app.store import APP_CONFIG, DEBUG_INFO

app = FastAPI(
    title="OpenClaw Debug Gate - Secure Coding MVP.",
    description="Training lab: find and fix broken authorization.",
    version="0.1.0",
)

class ConfigPatch(BaseModel):
    allow_debug_panel: bool | None = None
    command_prefix: str | None = None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "username": user.username,
        "role": user.role,
        "can_execute_command": user.can_execute_commands,
    }

@app.get("/commands/status")
def command_status(user: User = Depends(get_current_user)):
    require_command_access(user)

    return {
        "ok": True,
        "message": "Gateway command subsystem is online",
        "actor": user.username,
    }

@app.post("/command/ping")
def command_ping(user: User = Depends(get_current_user)):
    require_command_access(user)

    return {
        "ok": True,
        "pong": True,
        "actor": user.username,
    }

@app.get("/config")
def read_config(user: User = Depends(get_current_user)):
    require_owner(user)

    return {
        "config": APP_CONFIG,
        "actor": user.username,
    }

@app.patch("/config")
def patch_config(payload: ConfigPatch, user: User = Depends(get_current_user)):
    require_owner(user)

    if payload.allow_debug_panel is not None:
        APP_CONFIG["allow_debug_panel"] = payload.allow_debug_panel

    if payload.command_prefix is not None:
        APP_CONFIG["command_prefix"] = payload.command_prefix

    return {
        "ok": True,
        "config": APP_CONFIG,
        "actor": user.username,
    }

@app.get("/debug")
def  debug_info(user: User = Depends(get_current_user)):
    require_owner(user)

    return {
        "debug": DEBUG_INFO,
        "actor": user.username,
    }