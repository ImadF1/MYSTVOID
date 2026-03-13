from __future__ import annotations

from pathlib import Path

from agent.project_docs import build_agents_template, discover_instruction_files, load_instruction_context


def test_discover_instruction_files_finds_supported_names(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agent rules", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("claude notes", encoding="utf-8")

    files = discover_instruction_files(tmp_path)

    assert [path.name for path in files] == ["AGENTS.md", "CLAUDE.md"]


def test_load_instruction_context_includes_file_names(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("use pytest", encoding="utf-8")

    context = load_instruction_context(tmp_path, max_chars=200)

    assert "[AGENTS.md]" in context
    assert "use pytest" in context


def test_build_agents_template_mentions_project_name(tmp_path: Path) -> None:
    template = build_agents_template(tmp_path)

    assert f"# AGENTS.md for {tmp_path.name}" in template
    assert "## Common Commands" in template
