from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from agent.config import get_settings
from agent.loop import LocalCodingAgent
from agent.schemas import AgentRunResponse, ApprovalRequest, CreateSessionRequest, RunAgentRequest, SessionResponse
from agent.session_store import SessionStore
from tools.registry import TOOL_REGISTRY


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_DIR = PROJECT_ROOT / "ui"

settings = get_settings()
agent = LocalCodingAgent(settings=settings)
store = SessionStore()

app = FastAPI(
    title="MYSTVOID API",
    version="0.1.0",
    description="MYSTVOID: a local repository agent with Ollama, FastAPI, and a safe tool loop.",
)
app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "ollama_host": settings.ollama_host, "default_model": settings.default_model}


@app.get("/tools")
def tools() -> dict[str, list[dict[str, object]]]:
    return {
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "approval_kind": tool.approval_kind,
            }
            for tool in TOOL_REGISTRY.values()
        ]
    }


@app.post("/sessions", response_model=SessionResponse)
def create_session(request: CreateSessionRequest) -> SessionResponse:
    repo_path = Path(request.repo_path).expanduser().resolve()
    if not repo_path.exists():
        raise HTTPException(status_code=400, detail=f"Repository path does not exist: {repo_path}")
    if not repo_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Repository path is not a directory: {repo_path}")

    session = store.create_session(
        repo_path=repo_path,
        model=request.model or settings.default_model,
        auto_approve_writes=request.auto_approve_writes,
        auto_approve_commands=request.auto_approve_commands,
    )
    return store.to_response(session)


@app.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    try:
        session = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return store.to_response(session)


@app.post("/sessions/{session_id}/run", response_model=AgentRunResponse)
def run_agent(session_id: str, request: RunAgentRequest) -> AgentRunResponse:
    try:
        session = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if session.pending_approval is not None:
        raise HTTPException(status_code=409, detail="Session already has a pending approval.")
    try:
        return agent.run(session, request.message)
    except Exception as exc:
        return AgentRunResponse(session_id=session_id, status="error", error=str(exc))


@app.post("/sessions/{session_id}/approve", response_model=AgentRunResponse)
def approve_pending_action(session_id: str, request: ApprovalRequest) -> AgentRunResponse:
    try:
        session = store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    pending = session.pending_approval
    if pending is None:
        raise HTTPException(status_code=409, detail="Session does not have a pending approval.")
    if pending.approval_id != request.approval_id:
        raise HTTPException(status_code=400, detail="approval_id does not match the current pending action.")

    return agent.resume_after_approval(session, approve=request.approve)
