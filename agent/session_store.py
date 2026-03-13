from __future__ import annotations

import threading
from pathlib import Path

from agent.schemas import SessionResponse, SessionState


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionState] = {}

    def create_session(
        self,
        *,
        repo_path: Path,
        model: str,
        auto_approve_writes: bool,
        auto_approve_commands: bool,
    ) -> SessionState:
        session = SessionState(
            repo_path=repo_path,
            model=model,
            auto_approve_writes=auto_approve_writes,
            auto_approve_commands=auto_approve_commands,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionState:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown session_id: {session_id}")
        return session

    def to_response(self, session: SessionState) -> SessionResponse:
        return SessionResponse(
            session_id=session.session_id,
            repo_path=str(session.repo_path),
            model=session.model,
            auto_approve_writes=session.auto_approve_writes,
            auto_approve_commands=session.auto_approve_commands,
            has_pending_approval=session.pending_approval is not None,
        )
