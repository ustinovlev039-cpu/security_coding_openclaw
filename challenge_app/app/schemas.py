from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


LabStatusValue = Literal["Vulnerable", "Tests Running", "Tests Failed", "Lab Solved"]


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
