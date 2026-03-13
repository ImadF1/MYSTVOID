from __future__ import annotations

from pathlib import Path

from tools.filesystem import grep_symbol, list_files, open_file_at_line, read_file, read_many_files, search_code, write_file


def test_write_and_read_file(tmp_path: Path) -> None:
    message = "hello from local agent"
    write_file(tmp_path, "notes.txt", message)
    assert read_file(tmp_path, "notes.txt") == message


def test_list_files_returns_relative_paths(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    output = list_files(tmp_path, ".")
    assert "src\\app.py" in output or "src/app.py" in output


def test_search_code_finds_match(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("SAFE_TOKEN = 42\n", encoding="utf-8")
    output = search_code(tmp_path, "SAFE_TOKEN")
    assert "SAFE_TOKEN" in output


def test_read_many_files_and_open_file_at_line(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("line1\nline2\nline3\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("print('b')\n", encoding="utf-8")

    combined = read_many_files(tmp_path, ["a.py", "b.py"])
    focused = open_file_at_line(tmp_path, "a.py", 2, context=0)

    assert "## a.py" in combined
    assert "## b.py" in combined
    assert "2 | line2" in focused


def test_grep_symbol_matches_whole_word(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("SAFE_TOKEN = 1\nSAFE_TOKEN_EXTRA = 2\n", encoding="utf-8")

    output = grep_symbol(tmp_path, "SAFE_TOKEN")

    assert "SAFE_TOKEN = 1" in output
    assert "SAFE_TOKEN_EXTRA" not in output
