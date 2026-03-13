from __future__ import annotations

import subprocess
from pathlib import Path


def git_status(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--short", "--branch"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "git status failed"
        return f"git_status error: {stderr}"
    return result.stdout.strip() or "Working tree clean."


def git_diff(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "diff", "--", "."],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or "git diff failed"
        return f"git_diff error: {stderr}"
    return result.stdout.strip() or "No changes."
