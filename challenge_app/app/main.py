from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.hidden_validation import run_hidden_validation
from app.lab_config import (
    ALLOWED_FILE_PATHS,
    EDITABLE_FILE_PATHS,
    LAB_CATEGORY,
    LAB_TITLE,
    READABLE_FILE_PATHS,
    STATUS_LAB_SOLVED,
    STATUS_TESTS_FAILED,
    STATUS_TESTS_RUNNING,
    STATUS_VULNERABLE,
    WORKSPACE_DIR,
)
from app.runner import run_fixed_tests, run_gateway_simulation
from app.schemas import (
    CheckSolutionResponse,
    FileContentResponse,
    FileListResponse,
    FileUpdateRequest,
    FileUpdateResponse,
    GatewaySimulationRequest,
    GatewaySimulationResponse,
    LabStatusResponse,
    ResetResponse,
    TreeResponse,
    TestRunResponse,
    TestRunSummary,
)
from app.workspace import (
    ensure_workspace,
    is_editable_file,
    list_source_tree,
    list_allowed_files,
    read_allowed_file,
    read_state,
    reset_workspace,
    set_status,
    write_allowed_file,
)


app = FastAPI(
    title=LAB_TITLE,
    description="Security Coding lab for Broken Access Control in owner-only commands.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "PUT", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_workspace()


@app.get("/health")
def health() -> dict[str, str]:
    ensure_workspace()
    return {"status": "ok"}


def _status_response() -> LabStatusResponse:
    ensure_workspace()
    state = read_state()
    last_test = state.get("last_test")
    return LabStatusResponse(
        name=LAB_TITLE,
        category=LAB_CATEGORY,
        status=state.get("status", STATUS_VULNERABLE),
        workspace=str(WORKSPACE_DIR),
        allowed_files=list(ALLOWED_FILE_PATHS),
        editable_files=list(EDITABLE_FILE_PATHS),
        readable_files=list(READABLE_FILE_PATHS),
        last_test=TestRunSummary(**last_test) if isinstance(last_test, dict) else None,
        solved=bool(state.get("solved", False)),
    )


@app.get("/api/lab/status", response_model=LabStatusResponse)
def lab_status() -> LabStatusResponse:
    return _status_response()


@app.get("/api/lab/files", response_model=FileListResponse)
def lab_files() -> FileListResponse:
    return FileListResponse(files=list_allowed_files())


@app.get("/api/lab/tree", response_model=TreeResponse)
def lab_tree(path: str | None = None) -> TreeResponse:
    return TreeResponse(**list_source_tree(path))


@app.get("/api/lab/files/{file_path:path}", response_model=FileContentResponse)
def lab_file(file_path: str) -> FileContentResponse:
    return FileContentResponse(
        path=file_path,
        content=read_allowed_file(file_path),
        editable=is_editable_file(file_path),
    )


@app.put("/api/lab/files/{file_path:path}", response_model=FileUpdateResponse)
def update_lab_file(file_path: str, payload: FileUpdateRequest) -> FileUpdateResponse:
    normalized = write_allowed_file(file_path, payload.content)
    return FileUpdateResponse(path=normalized, saved=True, status=STATUS_VULNERABLE)


@app.post("/api/lab/run-tests", response_model=TestRunResponse)
def run_tests() -> TestRunResponse:
    workspace = ensure_workspace()
    set_status(STATUS_TESTS_RUNNING)
    result = run_fixed_tests(workspace)
    status = STATUS_VULNERABLE if result.ok else STATUS_TESTS_FAILED
    set_status(status, last_test=result.to_summary())
    return TestRunResponse(ok=result.ok, status=status, result=TestRunSummary(**result.to_summary()))


@app.post("/api/lab/reset", response_model=ResetResponse)
def reset_lab() -> ResetResponse:
    workspace = reset_workspace()
    return ResetResponse(status=STATUS_VULNERABLE, workspace=str(workspace))


@app.post("/api/lab/check-solution", response_model=CheckSolutionResponse)
def check_solution() -> CheckSolutionResponse:
    workspace = ensure_workspace()
    set_status(STATUS_TESTS_RUNNING)

    visible = run_fixed_tests(workspace)
    if not visible.ok:
        set_status(STATUS_TESTS_FAILED, last_test=visible.to_summary())
        return CheckSolutionResponse(
            ok=False,
            status=STATUS_TESTS_FAILED,
            visible_tests=TestRunSummary(**visible.to_summary()),
            hidden_validation_passed=False,
            hidden_validation="Hidden validation was not run because visible tests failed.",
        )

    hidden = run_hidden_validation(workspace)
    solved = hidden.ok
    status = STATUS_LAB_SOLVED if solved else STATUS_TESTS_FAILED
    set_status(status, last_test=visible.to_summary())

    return CheckSolutionResponse(
        ok=solved,
        status=status,
        visible_tests=TestRunSummary(**visible.to_summary()),
        hidden_validation_passed=solved,
        hidden_validation=(
            "Hidden validation passed."
            if solved
            else "Hidden validation failed. Preserve owner access, non-owner denial, and internal read-only config behavior."
        ),
    )


@app.post("/api/lab/gateway-simulate", response_model=GatewaySimulationResponse)
def gateway_simulate(payload: GatewaySimulationRequest) -> GatewaySimulationResponse:
    workspace = ensure_workspace()
    result = run_gateway_simulation(workspace, payload.role, payload.command)
    return GatewaySimulationResponse(**result.to_response())
