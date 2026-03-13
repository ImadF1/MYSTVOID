from __future__ import annotations

from pathlib import Path

from agent.config import Settings
from agent.loop import LocalCodingAgent
from agent.schemas import ModelDecision, SessionState


class StubLLM:
    def decide(self, *, model: str, system_prompt: str, messages: list[dict[str, str]]) -> ModelDecision:
        return ModelDecision(
            reasoning_summary="I can only work inside the configured repository root.",
            action="final",
            final_answer=None,
        )


class WriteStubLLM:
    def decide(self, *, model: str, system_prompt: str, messages: list[dict[str, str]]) -> ModelDecision:
        return ModelDecision(
            reasoning_summary="Create the requested file.",
            action="tool",
            tool_name="write_file",
            tool_input={"path": "notes.txt", "content": "hello\n"},
        )


def test_final_answer_falls_back_to_reasoning_summary(tmp_path: Path) -> None:
    agent = LocalCodingAgent(
        Settings(
            ollama_host="http://127.0.0.1:11434",
            default_model="qwen2.5-coder:latest",
            max_steps=4,
            command_timeout_seconds=30,
            max_file_chars=10000,
        )
    )
    agent.llm = StubLLM()
    session = SessionState(repo_path=tmp_path, model="qwen2.5-coder:latest")

    response = agent.run(session, "Create TEST.txt on my desktop")

    assert response.status == "completed"
    assert response.answer == "I can only work inside the configured repository root."
    assert response.steps[-1].observation == response.answer


def test_write_request_returns_pending_preview_by_default(tmp_path: Path) -> None:
    agent = LocalCodingAgent(
        Settings(
            ollama_host="http://127.0.0.1:11434",
            default_model="qwen2.5-coder:latest",
            max_steps=4,
            command_timeout_seconds=30,
            max_file_chars=10000,
        )
    )
    agent.llm = WriteStubLLM()
    session = SessionState(repo_path=tmp_path, model="qwen2.5-coder:latest")

    response = agent.run(session, "Create notes.txt")

    assert response.status == "needs_confirmation"
    assert response.pending_approval is not None
    assert response.pending_approval.tool_name == "write_file"
    assert "notes.txt" in (response.pending_approval.preview or "")
