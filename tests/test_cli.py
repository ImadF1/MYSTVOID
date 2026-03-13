from __future__ import annotations

from pathlib import Path

from agent.cli import (
    apply_queue_key,
    command_matches,
    create_session_from_args,
    describe_event,
    format_step,
    get_approval_mode,
    parse_args,
    parse_meta_command,
    parse_natural_navigation,
    resolve_model_choice,
    resolve_navigation_target,
    suggest_slash_command,
)
from agent.schemas import StepTrace


def test_parse_args_reads_terminal_flags() -> None:
    args = parse_args(
        [
            "--repo-path",
            "C:\\repo",
            "--model",
            "qwen2.5-coder:latest",
            "--theme",
            "midnight",
            "--approval-mode",
            "auto-edit",
            "--auto-approve-writes",
            "--show-steps",
            "--fresh",
            "explain",
            "repo",
        ]
    )
    assert args.repo_path == "C:\\repo"
    assert args.model == "qwen2.5-coder:latest"
    assert args.theme == "midnight"
    assert args.approval_mode == "auto-edit"
    assert args.auto_approve_writes is True
    assert args.auto_approve_commands is False
    assert args.show_steps is True
    assert args.setup is False
    assert args.fresh is True
    assert args.prompt == ["explain", "repo"]


def test_parse_meta_command_extracts_name_and_value() -> None:
    assert parse_meta_command("/model phi3:latest") == ("/model", "phi3:latest")
    assert parse_meta_command("/repo C:\\Work") == ("/repo", "C:\\Work")
    assert parse_meta_command("/") == ("/", "")
    assert parse_meta_command("plain prompt") is None


def test_parse_natural_navigation_extracts_target() -> None:
    assert parse_natural_navigation("go to Desktop") == "Desktop"
    assert parse_natural_navigation("cd ..") == ".."
    assert parse_natural_navigation("Explain this repo") is None


def test_format_step_includes_core_fields() -> None:
    step = StepTrace(
        iteration=2,
        reasoning_summary="Read the server file before answering.",
        action="tool",
        tool_name="read_file",
        tool_input={"path": "api/server.py"},
        observation="FastAPI app is created in api/server.py",
    )
    rendered = format_step(step)
    assert "[2] TOOL read_file" in rendered
    assert "api/server.py" in rendered
    assert "FastAPI app is created" in rendered


def test_create_session_from_args_uses_explicit_repo(tmp_path: Path) -> None:
    args = parse_args(["--repo-path", str(tmp_path), "--model", "phi3:latest"])
    session = create_session_from_args(args)

    assert session.repo_path == tmp_path.resolve()
    assert session.model == "phi3:latest"
    assert session.auto_approve_writes is False
    assert session.auto_approve_commands is False


def test_create_session_from_args_applies_approval_mode(tmp_path: Path) -> None:
    args = parse_args(["--repo-path", str(tmp_path), "--approval-mode", "full-auto"])
    session = create_session_from_args(args)

    assert get_approval_mode(session) == "full-auto"


def test_resolve_navigation_target_supports_relative_path(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()

    resolved = resolve_navigation_target("child", tmp_path)

    assert resolved == child.resolve()


def test_command_matches_filters_slash_commands() -> None:
    matches = command_matches("/mo")

    assert ("/model", "Show installed Ollama models and choose one") in matches
    assert ("/model NAME", "Set the Ollama model directly by name") in matches
    assert all(command.startswith("/") for command, _ in matches)


def test_command_matches_supports_approvals_alias() -> None:
    matches = command_matches("/app")

    assert ("/approvals [mode]", "Show or change approval mode: ask, auto-edit, full-auto") in matches


def test_suggest_slash_command_returns_ghost_text() -> None:
    assert suggest_slash_command("/mo") == "del"
    assert suggest_slash_command("/appro") == "vals [mode]"
    assert suggest_slash_command("/model phi3") is None


def test_resolve_model_choice_supports_number_and_name() -> None:
    models = ["phi3:latest", "qwen2.5-coder:latest"]

    assert resolve_model_choice("2", models) == "qwen2.5-coder:latest"
    assert resolve_model_choice("phi3:latest", models) == "phi3:latest"
    assert resolve_model_choice("9", models) is None


def test_apply_queue_key_builds_and_submits_message() -> None:
    buffer: list[str] = []
    queued_prompts: list[str] = []

    for key in "fix readme":
        apply_queue_key(buffer, queued_prompts, key)
    apply_queue_key(buffer, queued_prompts, "\r")

    assert buffer == []
    assert queued_prompts == ["fix readme"]


def test_describe_event_summarizes_tool_activity() -> None:
    assert describe_event({"kind": "decision"}) == "planning next step"
    assert describe_event({"kind": "tool_start", "tool_name": "read_file", "summary": "inspect README"}) == "read_file: inspect README"
