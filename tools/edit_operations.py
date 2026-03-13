from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from tools.safety import resolve_path


@dataclass(slots=True)
class PreparedEdit:
    path: str
    existed_before: bool
    before_content: str | None
    after_content: str
    summary: str
    created_at: str

    def to_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "PreparedEdit":
        return cls(
            path=str(payload["path"]),
            existed_before=bool(payload["existed_before"]),
            before_content=None if payload.get("before_content") is None else str(payload.get("before_content")),
            after_content=str(payload["after_content"]),
            summary=str(payload["summary"]),
            created_at=str(payload["created_at"]),
        )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(value: str, limit: int = 12000) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def build_diff_preview(path: str, before_content: str | None, after_content: str) -> str:
    before_lines = (before_content or "").splitlines(keepends=True)
    after_lines = after_content.splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    ).strip()
    return _truncate(diff or "No textual changes.")


def prepare_write(repo_root: Path, path: str, content: str) -> PreparedEdit:
    target = resolve_path(repo_root, path)
    before_content = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else None
    existed_before = target.exists()
    summary = f"{'Update' if existed_before else 'Create'} {target.relative_to(repo_root)}"
    return PreparedEdit(
        path=str(target.relative_to(repo_root)),
        existed_before=existed_before,
        before_content=before_content,
        after_content=content,
        summary=summary,
        created_at=_timestamp(),
    )


def prepare_patch(
    repo_root: Path,
    path: str,
    search_text: str,
    replace_text: str,
    *,
    replace_all: bool = False,
    expected_occurrences: int | None = None,
) -> PreparedEdit:
    if not search_text:
        raise ValueError("apply_patch search_text must not be empty.")

    target = resolve_path(repo_root, path)
    if not target.exists():
        raise FileNotFoundError(f"File does not exist: {path}")
    if not target.is_file():
        raise IsADirectoryError(f"Path is not a file: {path}")

    before_content = target.read_text(encoding="utf-8", errors="ignore")
    occurrences = before_content.count(search_text)
    if occurrences == 0:
        raise ValueError(f"search_text was not found in {path}.")
    if expected_occurrences is not None and occurrences != expected_occurrences:
        raise ValueError(f"Expected {expected_occurrences} occurrence(s), found {occurrences} in {path}.")
    if not replace_all and occurrences > 1 and expected_occurrences is None:
        raise ValueError(
            f"search_text matched {occurrences} times in {path}. "
            "Use expected_occurrences or replace_all to avoid ambiguous edits."
        )

    after_content = before_content.replace(
        search_text,
        replace_text,
        occurrences if replace_all else 1,
    )
    return PreparedEdit(
        path=str(target.relative_to(repo_root)),
        existed_before=True,
        before_content=before_content,
        after_content=after_content,
        summary=f"Patch {target.relative_to(repo_root)}",
        created_at=_timestamp(),
    )


def apply_prepared_edit(repo_root: Path, edit: PreparedEdit) -> str:
    target = resolve_path(repo_root, edit.path)
    current_content = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else None
    if current_content != edit.before_content:
        raise RuntimeError(
            f"File changed since the preview was generated: {edit.path}. "
            "Re-run the request to compute a fresh edit."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(edit.after_content, encoding="utf-8")
    return f"{edit.summary} ({len(edit.after_content)} character(s))."


def restore_prepared_edit(repo_root: Path, edit: PreparedEdit) -> str:
    target = resolve_path(repo_root, edit.path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if edit.existed_before:
        target.write_text(edit.before_content or "", encoding="utf-8")
        return f"Restored previous contents for {edit.path}."

    if target.exists():
        target.unlink()
        return f"Removed newly created file {edit.path}."

    return f"Nothing to undo for {edit.path}."
