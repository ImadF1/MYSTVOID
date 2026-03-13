from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from agent.config import Settings
from tools.filesystem import (
    grep_symbol,
    list_files,
    open_file_at_line,
    read_file,
    read_many_files,
    search_code,
    write_file,
)
from tools.git_tools import git_diff, git_status
from tools.safety import check_command_safety
from tools.shell import run_command, run_tests


ToolHandler = Callable[[Path, Settings, dict[str, Any]], str]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    approval_kind: Literal["none", "write", "command"] = "none"


def _read_file(repo_root: Path, settings: Settings, arguments: dict[str, Any]) -> str:
    return read_file(repo_root, str(arguments.get("path", "")), max_chars=settings.max_file_chars)


def _write_file(repo_root: Path, _settings: Settings, arguments: dict[str, Any]) -> str:
    return write_file(repo_root, str(arguments.get("path", "")), str(arguments.get("content", "")))


def _search_code(repo_root: Path, _settings: Settings, arguments: dict[str, Any]) -> str:
    return search_code(repo_root, str(arguments.get("query", "")))


def _grep_symbol(repo_root: Path, _settings: Settings, arguments: dict[str, Any]) -> str:
    return grep_symbol(repo_root, str(arguments.get("symbol", "")))


def _list_files(repo_root: Path, _settings: Settings, arguments: dict[str, Any]) -> str:
    return list_files(repo_root, str(arguments.get("directory", ".")))


def _read_many_files(repo_root: Path, settings: Settings, arguments: dict[str, Any]) -> str:
    raw_paths = arguments.get("paths", [])
    paths = [str(item) for item in raw_paths] if isinstance(raw_paths, list) else []
    return read_many_files(repo_root, paths, max_chars=settings.max_file_chars)


def _open_file_at_line(repo_root: Path, _settings: Settings, arguments: dict[str, Any]) -> str:
    return open_file_at_line(
        repo_root,
        str(arguments.get("path", "")),
        int(arguments.get("line", 1)),
        context=int(arguments.get("context", 20)),
    )


def _run_command(repo_root: Path, settings: Settings, arguments: dict[str, Any]) -> str:
    command = str(arguments.get("command", ""))
    safety = check_command_safety(command)
    return run_command(repo_root, safety.argv, timeout_seconds=settings.command_timeout_seconds)


def _run_tests(repo_root: Path, settings: Settings, _arguments: dict[str, Any]) -> str:
    return run_tests(repo_root, timeout_seconds=settings.command_timeout_seconds)


def _git_status(repo_root: Path, _settings: Settings, _arguments: dict[str, Any]) -> str:
    return git_status(repo_root)


def _git_diff(repo_root: Path, _settings: Settings, _arguments: dict[str, Any]) -> str:
    return git_diff(repo_root)


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "read_file": ToolDefinition(
        name="read_file",
        description="Read a UTF-8 text file relative to the repository root.",
        parameters={"path": "string"},
        handler=_read_file,
    ),
    "write_file": ToolDefinition(
        name="write_file",
        description="Write full UTF-8 content to a file relative to the repository root. Requires approval by default.",
        parameters={"path": "string", "content": "string"},
        handler=_write_file,
        approval_kind="write",
    ),
    "search_code": ToolDefinition(
        name="search_code",
        description="Search the repository with ripgrep and return matching lines.",
        parameters={"query": "string"},
        handler=_search_code,
    ),
    "grep_symbol": ToolDefinition(
        name="grep_symbol",
        description="Search the repository for a symbol using whole-word matching.",
        parameters={"symbol": "string"},
        handler=_grep_symbol,
    ),
    "list_files": ToolDefinition(
        name="list_files",
        description="List repository files under a directory.",
        parameters={"directory": "string"},
        handler=_list_files,
    ),
    "read_many_files": ToolDefinition(
        name="read_many_files",
        description="Read multiple text files in one call.",
        parameters={"paths": "string[]"},
        handler=_read_many_files,
    ),
    "open_file_at_line": ToolDefinition(
        name="open_file_at_line",
        description="Read a file around a specific 1-based line number with context.",
        parameters={"path": "string", "line": "integer", "context": "integer"},
        handler=_open_file_at_line,
    ),
    "run_command": ToolDefinition(
        name="run_command",
        description="Run a restricted repository command. Safe test/read-only commands run directly; other allowed commands require approval.",
        parameters={"command": "string"},
        handler=_run_command,
        approval_kind="command",
    ),
    "run_tests": ToolDefinition(
        name="run_tests",
        description="Detect and run the repository test command.",
        parameters={},
        handler=_run_tests,
    ),
    "git_status": ToolDefinition(
        name="git_status",
        description="Return git status for the repository working tree.",
        parameters={},
        handler=_git_status,
    ),
    "git_diff": ToolDefinition(
        name="git_diff",
        description="Return git diff for the repository working tree.",
        parameters={},
        handler=_git_diff,
    ),
    "apply_patch": ToolDefinition(
        name="apply_patch",
        description="Apply a targeted text replacement to an existing file. Prefer this over write_file for surgical edits.",
        parameters={
            "path": "string",
            "search_text": "string",
            "replace_text": "string",
            "replace_all": "boolean",
            "expected_occurrences": "integer",
        },
        handler=lambda _repo_root, _settings, _arguments: "apply_patch preview is handled by the agent loop.",
        approval_kind="write",
    ),
}


def render_tool_catalog() -> str:
    blocks: list[str] = []
    for tool in TOOL_REGISTRY.values():
        blocks.append(
            f"- {tool.name}: {tool.description}\n"
            f"  parameters: {tool.parameters}\n"
            f"  approval: {tool.approval_kind}"
        )
    return "\n".join(blocks)
