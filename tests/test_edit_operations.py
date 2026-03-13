from __future__ import annotations

from pathlib import Path

from tools.edit_operations import apply_prepared_edit, build_diff_preview, prepare_patch, prepare_write, restore_prepared_edit


def test_prepare_write_and_apply_create_file(tmp_path: Path) -> None:
    edit = prepare_write(tmp_path, "notes.txt", "hello\n")

    assert edit.existed_before is False
    assert "Create" in edit.summary
    assert "notes.txt" in build_diff_preview(edit.path, edit.before_content, edit.after_content)

    message = apply_prepared_edit(tmp_path, edit)

    assert "Create" in message
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello\n"


def test_prepare_patch_and_restore_previous_content(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("name = 'old'\n", encoding="utf-8")

    edit = prepare_patch(tmp_path, "app.py", "old", "new")
    apply_prepared_edit(tmp_path, edit)

    assert target.read_text(encoding="utf-8") == "name = 'new'\n"
    restore_message = restore_prepared_edit(tmp_path, edit)

    assert "Restored previous contents" in restore_message
    assert target.read_text(encoding="utf-8") == "name = 'old'\n"


def test_restore_prepared_edit_removes_new_file(tmp_path: Path) -> None:
    edit = prepare_write(tmp_path, "new.txt", "created")
    apply_prepared_edit(tmp_path, edit)

    restore_message = restore_prepared_edit(tmp_path, edit)

    assert "Removed newly created file" in restore_message
    assert not (tmp_path / "new.txt").exists()
