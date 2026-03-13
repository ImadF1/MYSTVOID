from __future__ import annotations

from pathlib import Path

import pytest

from tools.safety import SafetyError, check_command_safety, resolve_path


def test_resolve_path_stays_inside_repo(tmp_path: Path) -> None:
    safe_path = resolve_path(tmp_path, "src/app.py")
    assert safe_path == (tmp_path / "src" / "app.py").resolve()


def test_resolve_path_blocks_escape(tmp_path: Path) -> None:
    with pytest.raises(SafetyError):
        resolve_path(tmp_path, "..\\outside.txt")


def test_check_command_allows_pytest() -> None:
    result = check_command_safety("python -m pytest")
    assert result.requires_confirmation is False


def test_check_command_rejects_destructive_pattern() -> None:
    with pytest.raises(SafetyError):
        check_command_safety("git reset --hard")
