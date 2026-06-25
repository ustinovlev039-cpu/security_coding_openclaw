from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


LabStatusValue = Literal["Vulnerable", "Tests Running", "Tests Failed", "Lab Solved"]
GatewayRole = Literal["owner", "operator"]
GatewayCommand = Literal["config_show", "debug_show"]
GatewayOutcome = Literal["allowed", "blocked", "error"]


class TestRunSummary(BaseModel):
    ok: bool
    exit_code: int
    command: str
    output: str
    duration_ms: int


class LabStatusResponse(BaseModel):
    name: str
    category: str
    status: LabStatusValue
    workspace: str
    allowed_files: list[str]
    editable_files: list[str]
    readable_files: list[str]
    last_test: TestRunSummary | None = None
    solved: bool = False


class FileEntry(BaseModel):
    path: str
    name: str
    language: str
    editable: bool = True


class FileListResponse(BaseModel):
    files: list[FileEntry]


class FileContentResponse(BaseModel):
    path: str
    content: str
    editable: bool = True


class TreeEntry(BaseModel):
    path: str
    name: str
    type: Literal["file", "directory"]
    language: str | None = None
    editable: bool = False
    read_only: bool = True
    pinned: bool = False
    expandable: bool = False


class TreeResponse(BaseModel):
    path: str
    entries: list[TreeEntry]
    roots: list[str]
    pinned_paths: list[str]
    max_entries: int


class FileUpdateRequest(BaseModel):
    content: str = Field(max_length=1_000_000)


class FileUpdateResponse(BaseModel):
    path: str
    saved: bool
    status: LabStatusValue


class ResetResponse(BaseModel):
    status: LabStatusValue
    workspace: str


class TestRunResponse(BaseModel):
    ok: bool
    status: LabStatusValue
    result: TestRunSummary


class CheckSolutionResponse(BaseModel):
    ok: bool
    status: LabStatusValue
    visible_tests: TestRunSummary
    hidden_validation_passed: bool
    hidden_validation: str


class GatewaySimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: GatewayRole
    command: GatewayCommand


class GatewaySimulationResponse(BaseModel):
    ok: bool
    role: GatewayRole
    command: GatewayCommand
    display_command: str
    outcome: GatewayOutcome
    summary: str
    safe_output: str
    duration_ms: int
