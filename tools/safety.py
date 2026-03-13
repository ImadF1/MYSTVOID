from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


class SafetyError(ValueError):
    """Raised when an action is unsafe or outside the repository root."""


FORBIDDEN_COMMAND_SNIPPETS = [
    "&&",
    "||",
    ";",
    "|",
    ">",
    "<",
    " rm ",
    " del ",
    " rmdir ",
    " shutdown",
    " reboot",
    " format ",
    " mkfs",
    " git push",
    " git commit",
    " git reset",
    " git clean",
    " powershell -enc",
    " remove-item",
    " invoke-webrequest",
    " curl ",
    " wget ",
    " pip install",
    " python -c",
    " py -c",
    " start-process",
]

SAFE_PREFIXES: list[tuple[str, ...]] = [
    ("rg",),
    ("pytest",),
    ("py", "-m", "pytest"),
    ("python", "-m", "pytest"),
    ("py", "-m", "unittest"),
    ("python", "-m", "unittest"),
    ("py", "-m", "compileall"),
    ("python", "-m", "compileall"),
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "rev-parse"),
    ("git", "branch"),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("pnpm", "test"),
    ("pnpm", "run", "test"),
    ("uv", "run", "pytest"),
    ("cargo", "test"),
    ("go", "test"),
    ("dotnet", "test"),
]


@dataclass(slots=True)
class CommandSafetyResult:
    argv: list[str]
    requires_confirmation: bool
    reason: str | None = None


def resolve_path(repo_root: Path, raw_path: str) -> Path:
    candidate = (repo_root / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path).resolve()
    root = repo_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafetyError(f"Path '{raw_path}' is outside the repository root.") from exc
    return candidate


def parse_command(command: str) -> list[str]:
    argv = shlex.split(command, posix=(os.name != "nt"))
    if not argv:
        raise SafetyError("Command must not be empty.")
    return argv


def check_command_safety(command: str) -> CommandSafetyResult:
    normalized = f" {command.strip().lower()} "
    for snippet in FORBIDDEN_COMMAND_SNIPPETS:
        if snippet in normalized:
            raise SafetyError(f"Command contains a forbidden pattern: {snippet.strip()}")

    argv = parse_command(command)
    lowered = tuple(token.lower() for token in argv)
    if any(lowered[: len(prefix)] == prefix for prefix in SAFE_PREFIXES):
        return CommandSafetyResult(argv=argv, requires_confirmation=False)

    return CommandSafetyResult(
        argv=argv,
        requires_confirmation=True,
        reason="Command is not on the built-in safe allowlist and needs explicit approval.",
    )
