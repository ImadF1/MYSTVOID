from __future__ import annotations

from pathlib import Path

from agent.persistence import SessionPersistence
from agent.schemas import SessionState
from tools.edit_operations import prepare_write


def test_persistence_saves_and_loads_last_session(tmp_path: Path) -> None:
    persistence = SessionPersistence(tmp_path / "state")
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    session = SessionState(repo_path=repo_path, model="qwen2.5-coder:latest")
    session.conversation_history = [{"role": "user", "content": "Explain this repo"}]
    session.edit_history = [prepare_write(repo_path, "README.md", "# demo\n")]
    persistence.save(session)

    restored = persistence.load_last()

    assert restored is not None
    assert restored.repo_path == repo_path.resolve()
    assert restored.model == "qwen2.5-coder:latest"
    assert restored.conversation_history[0]["content"] == "Explain this repo"
    assert restored.edit_history[0].path == "README.md"
