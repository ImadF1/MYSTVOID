from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from agent.schemas import SessionState
from tools.edit_operations import PreparedEdit


def _default_state_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "MYSTVOID"
    return Path.home() / "AppData" / "Local" / "MYSTVOID"


class SessionPersistence:
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = (root_dir or _default_state_dir()).resolve()
        self.sessions_dir = self.root_dir / "sessions"
        self.last_session_path = self.root_dir / "last-session.json"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, session: SessionState) -> Path:
        session_path = self.sessions_dir / f"{session.session_id}.json"
        payload = {
            "session_id": session.session_id,
            "repo_path": str(session.repo_path),
            "model": session.model,
            "auto_approve_writes": session.auto_approve_writes,
            "auto_approve_commands": session.auto_approve_commands,
            "conversation_history": session.conversation_history,
            "edit_history": [edit.to_dict() for edit in session.edit_history],
        }
        session_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.last_session_path.write_text(
            json.dumps({"session_path": str(session_path), "repo_path": str(session.repo_path)}, indent=2),
            encoding="utf-8",
        )
        return session_path

    def load_last(self) -> SessionState | None:
        if not self.last_session_path.exists():
            return None
        try:
            payload = json.loads(self.last_session_path.read_text(encoding="utf-8"))
            session_path = Path(str(payload["session_path"]))
            return self.load_from_path(session_path)
        except Exception:
            return None

    def load_from_path(self, session_path: Path) -> SessionState | None:
        if not session_path.exists():
            return None
        payload = json.loads(session_path.read_text(encoding="utf-8"))
        session = SessionState(
            repo_path=Path(str(payload["repo_path"])).expanduser().resolve(),
            model=str(payload["model"]),
            auto_approve_writes=bool(payload.get("auto_approve_writes", False)),
            auto_approve_commands=bool(payload.get("auto_approve_commands", False)),
            conversation_history=[
                {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
                for item in payload.get("conversation_history", [])
                if isinstance(item, dict)
            ],
            edit_history=[
                PreparedEdit.from_dict(item)
                for item in payload.get("edit_history", [])
                if isinstance(item, dict)
            ],
            session_id=str(payload.get("session_id", "")) or uuid4().hex[:12],
        )
        return session

    def restore_into(self, session: SessionState, restored: SessionState, *, keep_explicit_model: bool) -> SessionState:
        session.conversation_history = restored.conversation_history
        session.edit_history = restored.edit_history
        session.auto_approve_writes = restored.auto_approve_writes
        session.auto_approve_commands = restored.auto_approve_commands
        if not keep_explicit_model:
            session.model = restored.model
        return session
