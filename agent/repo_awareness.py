from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from tools.shell import detect_test_command


IGNORED_NAMES = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}


def _render_entries(paths: list[Path]) -> str:
    return ", ".join(path.name for path in paths) if paths else "none"


@lru_cache(maxsize=32)
def build_repo_summary(repo_path_str: str) -> str:
    repo_path = Path(repo_path_str)
    entries = sorted(
        [item for item in repo_path.iterdir() if item.name not in IGNORED_NAMES],
        key=lambda item: (item.is_file(), item.name.lower()),
    )
    top_dirs = [item for item in entries if item.is_dir()][:10]
    top_files = [item for item in entries if item.is_file()][:10]
    important = [
        name
        for name in [
            "README.md",
            "pyproject.toml",
            "package.json",
            "Cargo.toml",
            "go.mod",
            "AGENTS.md",
            "CLAUDE.md",
        ]
        if (repo_path / name).exists()
    ]
    try:
        test_command = " ".join(detect_test_command(repo_path))
    except Exception:
        test_command = "unknown"

    return (
        f"Top-level directories: {_render_entries(top_dirs)}\n"
        f"Top-level files: {_render_entries(top_files)}\n"
        f"Important files: {', '.join(important) if important else 'none'}\n"
        f"Likely test command: {test_command}"
    )


def clear_repo_summary(repo_path: Path) -> None:
    build_repo_summary.cache_clear()
