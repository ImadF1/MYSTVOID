from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from tools.edit_operations import PreparedEdit, prepare_patch, prepare_write
from tools.safety import resolve_path


def _truncate(value: str, limit: int = 20000) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def read_file(repo_root: Path, path: str, max_chars: int = 30000) -> str:
    target = resolve_path(repo_root, path)
    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {path}")
    if not target.is_file():
        raise IsADirectoryError(f"Path is not a file: {path}")
    return _truncate(target.read_text(encoding="utf-8", errors="ignore"), max_chars)


def write_file(repo_root: Path, path: str, content: str) -> str:
    target = resolve_path(repo_root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} character(s) to {target.relative_to(repo_root)}."


def list_files(repo_root: Path, directory: str = ".", max_results: int = 400) -> str:
    target = resolve_path(repo_root, directory)
    if not target.exists():
        raise FileNotFoundError(f"Directory does not exist: {directory}")
    if not target.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {directory}")

    try:
        result = subprocess.run(
            ["rg", "--files", str(target), "--glob", "!.git", "--glob", "!.venv", "--glob", "!node_modules"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode not in (0, 1):
            raise RuntimeError(result.stderr.strip() or "rg --files failed")
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return "No files found."
        relative_lines: list[str] = []
        for item in lines[:max_results]:
            relative_lines.append(str(Path(item).resolve().relative_to(repo_root.resolve())))
        return "\n".join(relative_lines)
    except FileNotFoundError:
        collected: list[str] = []
        for root, dirs, files in os.walk(target):
            dirs[:] = [name for name in dirs if name not in {".git", "__pycache__", ".venv", "node_modules"}]
            for filename in files:
                path_obj = Path(root, filename).resolve()
                collected.append(str(path_obj.relative_to(repo_root.resolve())))
                if len(collected) >= max_results:
                    return "\n".join(collected)
        return "\n".join(collected) if collected else "No files found."


def search_code(repo_root: Path, query: str, max_results: int = 200) -> str:
    if not query.strip():
        raise ValueError("search_code query must not be empty.")

    try:
        result = subprocess.run(
            ["rg", "-n", "--glob", "!.git", "--glob", "!.venv", "--glob", "!node_modules", query, str(repo_root)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ripgrep (rg) is required for search_code but was not found in PATH.") from exc

    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "ripgrep failed")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return "No matches found."
    return _truncate("\n".join(lines[:max_results]), 20000)


def read_many_files(repo_root: Path, paths: list[str], max_chars: int = 30000) -> str:
    if not paths:
        raise ValueError("read_many_files paths must not be empty.")

    blocks: list[str] = []
    remaining = max_chars
    for raw_path in paths[:8]:
        content = read_file(repo_root, raw_path, max_chars=min(remaining, max_chars))
        block = f"## {raw_path}\n{content}"
        if len(block) > remaining:
            block = _truncate(block, remaining)
        blocks.append(block)
        remaining -= len(block) + 2
        if remaining <= 0:
            break
    return "\n\n".join(blocks)


def open_file_at_line(repo_root: Path, path: str, line: int, context: int = 20) -> str:
    if line < 1:
        raise ValueError("line must be >= 1.")
    target = resolve_path(repo_root, path)
    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {path}")
    if not target.is_file():
        raise IsADirectoryError(f"Path is not a file: {path}")

    lines = target.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = max(1, line - context)
    end = min(len(lines), line + context)
    rendered = [
        f"{number:>5} | {lines[number - 1]}"
        for number in range(start, end + 1)
    ]
    return "\n".join(rendered) if rendered else "File is empty."


def grep_symbol(repo_root: Path, symbol: str, max_results: int = 100) -> str:
    if not symbol.strip():
        raise ValueError("grep_symbol symbol must not be empty.")
    pattern = rf"\b{re.escape(symbol)}\b"
    try:
        result = subprocess.run(
            ["rg", "-n", "--glob", "!.git", "--glob", "!.venv", "--glob", "!node_modules", "--pcre2", pattern, str(repo_root)],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ripgrep (rg) is required for grep_symbol but was not found in PATH.") from exc

    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "ripgrep failed")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return "No symbol matches found."
    return _truncate("\n".join(lines[:max_results]), 20000)


def preview_write(repo_root: Path, path: str, content: str) -> PreparedEdit:
    return prepare_write(repo_root, path, content)


def preview_patch(
    repo_root: Path,
    path: str,
    search_text: str,
    replace_text: str,
    *,
    replace_all: bool = False,
    expected_occurrences: int | None = None,
) -> PreparedEdit:
    return prepare_patch(
        repo_root,
        path,
        search_text,
        replace_text,
        replace_all=replace_all,
        expected_occurrences=expected_occurrences,
    )
