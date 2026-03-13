from __future__ import annotations

from pathlib import Path


INSTRUCTION_FILENAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CLAUDE.local.md",
)


def discover_instruction_files(repo_path: Path) -> list[Path]:
    return [path for name in INSTRUCTION_FILENAMES if (path := repo_path / name).is_file()]


def load_instruction_context(repo_path: Path, *, max_chars: int = 6000) -> str:
    files = discover_instruction_files(repo_path)
    if not files:
        return ""

    blocks: list[str] = []
    remaining = max_chars
    for path in files:
        if remaining <= 0:
            break

        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            continue

        header = f"[{path.name}]\n"
        budget = max(0, remaining - len(header))
        snippet = content[:budget].strip()
        if len(snippet) < len(content):
            snippet = snippet[: max(0, len(snippet) - 3)] + "..."

        blocks.append(header + snippet)
        remaining -= len(blocks[-1]) + 2

    return "\n\n".join(blocks)


def build_agents_template(repo_path: Path) -> str:
    project_name = repo_path.name or "project"
    return (
        f"# AGENTS.md for {project_name}\n\n"
        "## Project Overview\n"
        "- Describe the purpose of this repository.\n"
        "- Mention the main app entrypoints.\n\n"
        "## Common Commands\n"
        "- Build: add the main build command here.\n"
        "- Test: add the main test command here.\n"
        "- Lint: add the lint or formatting command here.\n\n"
        "## Coding Preferences\n"
        "- Describe naming conventions and style rules.\n"
        "- Note important architecture or folder patterns.\n\n"
        "## Safety Notes\n"
        "- Document files or directories that should be treated carefully.\n"
        "- Note commands that should not be run automatically.\n"
    )
