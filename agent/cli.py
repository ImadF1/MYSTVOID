from __future__ import annotations

import argparse
import json
import msvcrt
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from time import sleep
from typing import Any, Callable, Literal, Sequence

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from agent.config import Settings, get_settings
from agent.loop import LocalCodingAgent
from agent.ollama_client import list_installed_models
from agent.persistence import SessionPersistence
from agent.project_docs import build_agents_template, discover_instruction_files
from agent.repo_awareness import clear_repo_summary
from agent.schemas import AgentRunResponse, PendingApproval, SessionState, StepTrace
from agent.session_store import SessionStore
from tools.shell import run_tests as run_repo_tests
from tools.edit_operations import PreparedEdit, build_diff_preview, restore_prepared_edit
from tools.registry import TOOL_REGISTRY


ApprovalMode = Literal["ask", "auto-edit", "full-auto"]
ThemeName = Literal["amber", "midnight", "forest", "mono", "light"]

APP_NAME = "MYSTVOID"
THEME_PALETTES: dict[ThemeName, dict[str, str]] = {
    "amber": {
        "brand": "bold #c77827",
        "accent": "#9a3412",
        "soft": "#e7d7c5",
        "muted": "#8a7565",
        "success": "#15803d",
        "warning": "#c2410c",
        "danger": "#b91c1c",
        "info": "#0f766e",
        "prompt": "#d97706 bold",
        "dim": "bright_black",
    },
    "midnight": {
        "brand": "bold #60a5fa",
        "accent": "#1d4ed8",
        "soft": "#dbeafe",
        "muted": "#7c93b7",
        "success": "#22c55e",
        "warning": "#f59e0b",
        "danger": "#ef4444",
        "info": "#38bdf8",
        "prompt": "#93c5fd bold",
        "dim": "bright_black",
    },
    "forest": {
        "brand": "bold #22c55e",
        "accent": "#15803d",
        "soft": "#dcfce7",
        "muted": "#6b8a72",
        "success": "#16a34a",
        "warning": "#ca8a04",
        "danger": "#dc2626",
        "info": "#0f766e",
        "prompt": "#4ade80 bold",
        "dim": "bright_black",
    },
    "mono": {
        "brand": "bold white",
        "accent": "bright_white",
        "soft": "white",
        "muted": "grey70",
        "success": "bright_white",
        "warning": "grey70",
        "danger": "white",
        "info": "grey70",
        "prompt": "bold white",
        "dim": "bright_black",
    },
    "light": {
        "brand": "bold #8a3b12",
        "accent": "#b45309",
        "soft": "#3f2d22",
        "muted": "#7c5f4d",
        "success": "#166534",
        "warning": "#b45309",
        "danger": "#b91c1c",
        "info": "#0f766e",
        "prompt": "#92400e bold",
        "dim": "grey50",
    },
}
DEFAULT_THEME_NAME: ThemeName = "amber"
PROMPT_STYLE_MAP: dict[ThemeName, dict[str, str]] = {
    "amber": {
        "prompt": "bold fg:#d97706",
        "muted": "fg:#8a7565",
        "menu": "bg:#9a3412 fg:#e7d7c5",
        "menu_current": "bg:#c77827 fg:#fef3c7 bold",
    },
    "midnight": {
        "prompt": "bold fg:#93c5fd",
        "muted": "fg:#7c93b7",
        "menu": "bg:#1d4ed8 fg:#dbeafe",
        "menu_current": "bg:#60a5fa fg:#0f172a bold",
    },
    "forest": {
        "prompt": "bold fg:#4ade80",
        "muted": "fg:#6b8a72",
        "menu": "bg:#15803d fg:#dcfce7",
        "menu_current": "bg:#22c55e fg:#052e16 bold",
    },
    "mono": {
        "prompt": "bold fg:#ffffff",
        "muted": "fg:#9ca3af",
        "menu": "bg:#111827 fg:#ffffff",
        "menu_current": "bg:#374151 fg:#ffffff bold",
    },
    "light": {
        "prompt": "bold fg:#92400e",
        "muted": "fg:#7c5f4d",
        "menu": "bg:#f3e8d8 fg:#3f2d22",
        "menu_current": "bg:#d6b48a fg:#2b2118 bold",
    },
}


def build_console(theme_name: ThemeName) -> Console:
    return Console(theme=Theme(THEME_PALETTES[theme_name]), highlight=False, soft_wrap=True)


console = build_console(DEFAULT_THEME_NAME)

NAVIGATION_PATTERNS = (
    re.compile(r"^\s*(?:go to|goto|switch to|cd|enter)\s+(.+?)\s*$", re.IGNORECASE),
)
OPEN_PATTERN = re.compile(r"^(?P<path>.+?)(?::(?P<line>\d+))?$")
COMMAND_ROWS: tuple[tuple[str, str], ...] = (
    ("/help", "Show available commands"),
    ("/", "Show slash commands"),
    ("/status", "Show repo, model, approvals, summary, and edit count"),
    ("/repo PATH", "Switch working repository and clear chat history"),
    ("go to Desktop", "Natural navigation aliases such as Desktop, Downloads, Documents, or relative paths"),
    ("/model", "Show installed Ollama models and choose one"),
    ("/model NAME", "Set the Ollama model directly by name"),
    ("/theme NAME", "Show or change the terminal theme: amber, midnight, forest, mono, light"),
    ("/approvals [mode]", "Show or change approval mode: ask, auto-edit, full-auto"),
    ("/memory", "List loaded project instruction files"),
    ("/init", "Create a starter AGENTS.md in the current repo"),
    ("/run-tests", "Run the detected test command directly"),
    ("/open PATH[:LINE]", "Read a file or a section around a line"),
    ("/search QUERY", "Run repository ripgrep directly"),
    ("/files [DIR]", "List repository files directly"),
    ("/diff", "Show the current git diff"),
    ("/git", "Show git status"),
    ("/undo", "Undo the most recent approved file edit"),
    ("/checkpoints", "List saved edit checkpoints"),
    ("/history [term]", "Search recent chat history"),
    ("/steps", "Show the last detailed tool trace"),
    ("/verbose on|off", "Toggle step traces after each reply"),
    ("/new", "Start a new chat in the current repo"),
    ("/save", "Force-save the current session snapshot"),
    ("/clear", "Alias for /new"),
    ("/exit", "Quit the terminal app"),
)


@dataclass(slots=True)
class CliState:
    show_steps: bool = False
    last_response: AgentRunResponse | None = None
    restored_session: bool = False
    theme_name: ThemeName = DEFAULT_THEME_NAME
    prompt_session: Any | None = None


def set_active_theme(theme_name: ThemeName) -> None:
    global console
    console = build_console(theme_name)


def slash_commands() -> list[str]:
    return [command_name for command_name, _ in COMMAND_ROWS if command_name.startswith("/")]


def suggest_slash_command(raw_text: str) -> str | None:
    text = raw_text.strip()
    if not text.startswith("/") or " " in text:
        return None
    lowered = text.lower()
    for command_name in slash_commands():
        if command_name.lower().startswith(lowered) and command_name.lower() != lowered:
            return command_name[len(text) :]
    return None


def build_prompt_session(theme_name: ThemeName) -> Any | None:
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.output.win32 import NoConsoleScreenBufferError
        from prompt_toolkit.styles import Style
    except ImportError:
        return None

    prompt_style = PROMPT_STYLE_MAP[theme_name]

    class SlashAutoSuggest(AutoSuggest):
        def get_suggestion(self, buffer: Any, document: Any) -> Any | None:
            suggestion = suggest_slash_command(document.text)
            if suggestion is None:
                return None
            return Suggestion(suggestion)

    class SlashCompleter(Completer):
        def get_completions(self, document: Any, complete_event: Any) -> Any:
            text = document.text_before_cursor
            if not text.startswith("/"):
                return
            lowered = text.lower()
            for command_name in slash_commands():
                if command_name.lower().startswith(lowered) and command_name.lower() != lowered:
                    yield Completion(
                        command_name,
                        start_position=-len(text),
                        display=command_name,
                    )

    style = Style.from_dict(
        {
            "prompt": prompt_style["prompt"],
            "auto-suggestion": prompt_style["muted"],
            "completion-menu": prompt_style["menu"],
            "completion-menu.completion.current": prompt_style["menu_current"],
        }
    )
    try:
        return PromptSession(
            history=InMemoryHistory(),
            auto_suggest=SlashAutoSuggest(),
            completer=SlashCompleter(),
            complete_while_typing=True,
            reserve_space_for_menu=6,
            style=style,
        )
    except NoConsoleScreenBufferError:
        return None


def prompt_for_user_input(cli_state: CliState) -> str:
    session = cli_state.prompt_session
    if session is not None:
        return str(session.prompt(f"{APP_NAME} > ")).strip()
    return Prompt.ask(Text(f"{APP_NAME} >", style="prompt"), console=console).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mystvoid",
        description="Use the MYSTVOID repository agent from a terminal REPL.",
    )
    parser.add_argument("prompt", nargs="*", help="Optional one-shot prompt to run immediately.")
    parser.add_argument("--repo-path", help="Repository path for the session.")
    parser.add_argument("--model", help="Local Ollama model to use.")
    parser.add_argument(
        "--theme",
        choices=["amber", "midnight", "forest", "mono", "light"],
        default=DEFAULT_THEME_NAME,
        help="Terminal theme.",
    )
    parser.add_argument(
        "--approval-mode",
        choices=["ask", "auto-edit", "full-auto"],
        default="ask",
        help="ask = confirm writes and non-safe commands, auto-edit = auto-approve writes, full-auto = auto-approve both.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Prompt for repo, model, and approval settings before starting.",
    )
    parser.add_argument(
        "--show-steps",
        action="store_true",
        help="Always print detailed tool traces after each response.",
    )
    parser.add_argument(
        "--auto-approve-writes",
        action="store_true",
        help="Allow write_file without interactive confirmation.",
    )
    parser.add_argument(
        "--auto-approve-commands",
        action="store_true",
        help="Allow non-safe run_command calls without interactive confirmation.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Start a fresh session instead of restoring the last saved session for the same repo.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def parse_meta_command(raw: str) -> tuple[str, str] | None:
    command = raw.strip()
    if not command.startswith("/"):
        return None
    name, _, value = command.partition(" ")
    return name.lower(), value.strip()


def parse_natural_navigation(raw: str) -> str | None:
    for pattern in NAVIGATION_PATTERNS:
        match = pattern.fullmatch(raw)
        if match:
            return match.group(1).strip()
    return None


def resolve_repo_path(raw_value: str) -> Path:
    repo_path = Path(raw_value).expanduser().resolve()
    if not repo_path.exists():
        raise ValueError(f"Repository path does not exist: {repo_path}")
    if not repo_path.is_dir():
        raise ValueError(f"Repository path must be a directory: {repo_path}")
    return repo_path


def resolve_navigation_target(raw_value: str, current_repo: Path) -> Path:
    target = raw_value.strip().strip("\"'").rstrip(".")
    aliases = {
        "desktop": Path.home() / "Desktop",
        "downloads": Path.home() / "Downloads",
        "documents": Path.home() / "Documents",
        "home": Path.home(),
        "~": Path.home(),
    }
    alias_path = aliases.get(target.lower())
    if alias_path is not None:
        return resolve_repo_path(str(alias_path))

    candidate = Path(target).expanduser()
    if candidate.is_absolute():
        return resolve_repo_path(str(candidate))
    return resolve_repo_path(str((current_repo / candidate).resolve()))


def resolve_model_choice(selection: str, models: list[str]) -> str | None:
    value = selection.strip()
    if not value:
        return None
    if value.isdigit():
        index = int(value) - 1
        if 0 <= index < len(models):
            return models[index]
        return None
    return value if value in models else None


def apply_queue_key(buffer: list[str], queued_prompts: list[str], key: str) -> None:
    if key in {"\x00", "\xe0"}:
        return
    if key in {"\r", "\n"}:
        queued = "".join(buffer).strip()
        buffer.clear()
        if queued:
            queued_prompts.append(queued)
        return
    if key == "\x08":
        if buffer:
            buffer.pop()
        return
    if key == "\x1b":
        buffer.clear()
        return
    if key.isprintable():
        buffer.append(key)


def describe_event(event: dict[str, str]) -> str:
    kind = event.get("kind")
    if kind == "decision":
        return "planning next step"
    if kind == "tool_start":
        tool_name = event.get("tool_name", "tool")
        summary = clip_text(event.get("summary", ""), 48)
        return f"{tool_name}: {summary}" if summary else f"{tool_name}"
    if kind == "tool_result":
        tool_name = event.get("tool_name", "tool")
        return f"finished {tool_name}"
    return ""


def build_queue_status(action_label: str, buffer: list[str], queued_prompts: list[str], detail: str = "") -> str:
    message = f"[brand]{action_label}...[/brand]"
    hint = "Type and press Enter to queue the next message."
    parts = [hint]
    if detail:
        parts.insert(0, detail)
    if queued_prompts:
        parts.append(f"{len(queued_prompts)} queued")
    if buffer:
        parts.append(f"typing: {clip_text(''.join(buffer), 50)}")
    return f"{message} [muted]{' | '.join(parts)}[/muted]"


def prompt_text(label: str, default: str) -> str:
    return Prompt.ask(Text(label, style="soft"), default=default, console=console).strip()


def prompt_yes_no(label: str, default: bool = False) -> bool:
    return Confirm.ask(Text(label, style="soft"), default=default, console=console)


def clip_text(value: str | None, limit: int = 320) -> str:
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def format_step(step: StepTrace) -> str:
    action_label = step.action.upper()
    parts = [f"[{step.iteration}] {action_label}"]
    if step.tool_name:
        parts[0] += f" {step.tool_name}"
    if step.reasoning_summary:
        parts.append(f"  why: {step.reasoning_summary}")
    if step.tool_input:
        parts.append(f"  input: {clip_text(json.dumps(step.tool_input, ensure_ascii=False), 280)}")
    if step.observation:
        parts.append(f"  result: {clip_text(step.observation, 320)}")
    return "\n".join(parts)


def format_pending(pending: PendingApproval) -> str:
    return "\n".join(
        [
            f"tool: {pending.tool_name}",
            f"kind: {pending.approval_kind}",
            f"reason: {pending.reason}",
            f"message: {pending.message}",
            f"input: {clip_text(json.dumps(pending.tool_input, ensure_ascii=False), 260)}",
        ]
    )


def get_approval_mode(session: SessionState) -> ApprovalMode:
    if session.auto_approve_writes and session.auto_approve_commands:
        return "full-auto"
    if session.auto_approve_writes:
        return "auto-edit"
    return "ask"


def apply_approval_mode(session: SessionState, mode: ApprovalMode) -> None:
    if mode == "ask":
        session.auto_approve_writes = False
        session.auto_approve_commands = False
    elif mode == "auto-edit":
        session.auto_approve_writes = True
        session.auto_approve_commands = False
    else:
        session.auto_approve_writes = True
        session.auto_approve_commands = True


def normalize_theme_name(raw_value: str) -> ThemeName:
    theme_name = raw_value.strip().lower()
    if theme_name not in THEME_PALETTES:
        raise ValueError("Theme must be one of: amber, midnight, forest, mono, light.")
    return theme_name  # type: ignore[return-value]


def summarize_steps(steps: list[StepTrace]) -> str:
    labels: list[str] = []
    for step in steps:
        labels.append(step.tool_name or step.action)
    return " -> ".join(labels[:5]) + (" -> ..." if len(labels) > 5 else "")


def print_welcome(session: SessionState, cli_state: CliState) -> None:
    title = Text(APP_NAME, style="brand")
    body = Table.grid(padding=(0, 1))
    body.add_column(style="muted")
    body.add_column(style="soft")
    body.add_row("Repository", str(session.repo_path))
    body.add_row("Model", session.model)
    body.add_row("Approval", get_approval_mode(session))
    body.add_row("Theme", cli_state.theme_name)
    body.add_row("Memory", str(len(discover_instruction_files(session.repo_path))) + " loaded")
    body.add_row("Edits", str(len(session.edit_history)))
    body.add_row("Verbose", "on" if cli_state.show_steps else "off")
    body.add_row("Session", "restored" if cli_state.restored_session else "new")

    console.print(Panel(body, title=title, border_style="brand", padding=(1, 2)))
    console.print("[muted]Type /help for commands. Ask naturally and work directly in the terminal.[/muted]")


def print_help() -> None:
    table = Table(title="Commands", border_style="brand", show_header=True, header_style="brand")
    table.add_column("Command", style="soft", no_wrap=True)
    table.add_column("Purpose", style="muted")
    for command_name, description in COMMAND_ROWS:
        table.add_row(command_name, description)
    console.print(table)


def command_matches(prefix: str) -> list[tuple[str, str]]:
    normalized = prefix.strip().lower()
    if not normalized or normalized == "/":
        return [row for row in COMMAND_ROWS if row[0].startswith("/")]
    return [row for row in COMMAND_ROWS if row[0].lower().startswith(normalized)]


def print_command_matches(prefix: str) -> None:
    matches = command_matches(prefix)
    if not matches:
        console.print(f"[warning]No commands match {prefix}.[/warning]")
        return
    table = Table(
        title="Slash Commands" if prefix.strip() in {"", "/"} else f"Matches for {prefix}",
        border_style="brand",
        show_header=True,
        header_style="brand",
    )
    table.add_column("Command", style="soft", no_wrap=True)
    table.add_column("Purpose", style="muted")
    for command_name, description in matches:
        if command_name.startswith("/"):
            table.add_row(command_name, description)
    console.print(table)


def print_status(session: SessionState, cli_state: CliState) -> None:
    files = discover_instruction_files(session.repo_path)
    body = Table.grid(padding=(0, 1))
    body.add_column(style="muted")
    body.add_column(style="soft")
    body.add_row("Session", session.session_id)
    body.add_row("Repository", str(session.repo_path))
    body.add_row("Model", session.model)
    body.add_row("Approval", get_approval_mode(session))
    body.add_row("Theme", cli_state.theme_name)
    body.add_row("Conversation turns", str(len(session.conversation_history)))
    body.add_row("Pending approval", "yes" if session.pending_approval else "no")
    body.add_row("Edit checkpoints", str(len(session.edit_history)))
    body.add_row("Verbose", "on" if cli_state.show_steps else "off")
    body.add_row("Memory files", ", ".join(path.name for path in files) if files else "none")
    console.print(Panel(body, title="Status", border_style="info"))


def print_memory(session: SessionState) -> None:
    files = discover_instruction_files(session.repo_path)
    if not files:
        console.print(
            Panel(
                "No project instruction files found in this repository.\nUse /init to create a starter AGENTS.md.",
                title="Memory",
                border_style="warning",
            )
        )
        return

    table = Table(title="Loaded Memory Files", border_style="brand", header_style="brand")
    table.add_column("File", style="soft")
    table.add_column("Path", style="muted")
    for path in files:
        table.add_row(path.name, str(path))
    console.print(table)


def print_steps(cli_state: CliState) -> None:
    response = cli_state.last_response
    if response is None or not response.steps:
        console.print("[muted]No previous step trace is available yet.[/muted]")
        return
    console.print(Panel("\n".join(format_step(step) for step in response.steps), title="Last Tool Trace", border_style="muted"))


def print_checkpoints(session: SessionState) -> None:
    if not session.edit_history:
        console.print("[muted]No edit checkpoints are available yet.[/muted]")
        return

    table = Table(title="Edit Checkpoints", border_style="brand", header_style="brand")
    table.add_column("#", style="muted", width=4)
    table.add_column("Path", style="soft")
    table.add_column("Summary", style="soft")
    table.add_column("Timestamp", style="muted")
    for index, edit in enumerate(reversed(session.edit_history[-10:]), start=1):
        table.add_row(str(index), edit.path, edit.summary, edit.created_at)
    console.print(table)


def print_history(session: SessionState, query: str) -> None:
    rows = session.conversation_history[-20:]
    if query:
        rows = [item for item in rows if query.lower() in item.get("content", "").lower()]
    if not rows:
        console.print("[muted]No chat history matches.[/muted]")
        return
    table = Table(title="Recent History", border_style="muted")
    table.add_column("Role", style="soft", width=10)
    table.add_column("Content", style="muted")
    for item in rows:
        table.add_row(item.get("role", ""), clip_text(item.get("content", ""), 200))
    console.print(table)


def fetch_local_models(settings: Settings) -> list[str]:
    return list_installed_models(settings.ollama_host)


def print_model_list(settings: Settings, current_model: str) -> list[str]:
    try:
        models = fetch_local_models(settings)
    except Exception as exc:
        console.print(f"[danger]Could not load installed models:[/danger] {exc}")
        return []

    if not models:
        console.print("[warning]No local Ollama models were found.[/warning]")
        return []

    table = Table(title="Installed Models", border_style="brand", header_style="brand")
    table.add_column("#", style="muted", width=4)
    table.add_column("Model", style="soft")
    table.add_column("Current", style="muted", width=9)
    for index, model_name in enumerate(models, start=1):
        table.add_row(str(index), model_name, "yes" if model_name == current_model else "")
    console.print(table)
    return models


def choose_model_interactively(session: SessionState, settings: Settings, persistence: SessionPersistence) -> None:
    models = print_model_list(settings, session.model)
    if not models:
        return

    selection = Prompt.ask(
        Text("Choose a model number, exact name, or press Enter to keep the current model", style="soft"),
        default="",
        console=console,
    ).strip()
    if not selection:
        return

    resolved = resolve_model_choice(selection, models)
    if resolved is None:
        console.print("[danger]That selection does not match an installed model.[/danger]")
        return
    session.model = resolved

    persistence.save(session)
    console.print(f"[success]Model updated to {session.model}[/success]")


def render_preview_panel(pending: PendingApproval) -> Panel | None:
    if not pending.preview:
        return None
    if pending.approval_kind == "write":
        return Panel(
            Syntax(pending.preview, "diff", line_numbers=False, word_wrap=True),
            title="Edit Preview",
            border_style="warning",
        )
    return Panel(pending.preview, title="Command Preview", border_style="warning")


def print_response(response: AgentRunResponse, *, show_steps: bool) -> None:
    if response.answer:
        console.print(
            Panel(
                Markdown(response.answer),
                title="Assistant",
                subtitle=summarize_steps(response.steps) if response.steps else None,
                border_style="brand",
                padding=(1, 2),
            )
        )

    if response.error:
        console.print(Panel(response.error, title="Error", border_style="danger"))

    if response.pending_approval is not None:
        console.print(Panel(format_pending(response.pending_approval), title="Pending Approval", border_style="warning"))
        preview_panel = render_preview_panel(response.pending_approval)
        if preview_panel is not None:
            console.print(preview_panel)

    if show_steps and response.steps:
        print_steps(CliState(show_steps=show_steps, last_response=response))
    elif response.steps:
        console.print(f"[muted]Used {len(response.steps)} steps. Use /steps or /verbose on to inspect details.[/muted]")


def handle_init(session: SessionState, persistence: SessionPersistence) -> None:
    target = session.repo_path / "AGENTS.md"
    if target.exists():
        console.print(f"[warning]{target} already exists.[/warning]")
        return
    if not prompt_yes_no(f"Create {target.name} in {session.repo_path}?", default=True):
        console.print("[muted]Cancelled.[/muted]")
        return
    target.write_text(build_agents_template(session.repo_path), encoding="utf-8")
    clear_repo_summary(session.repo_path)
    persistence.save(session)
    console.print(f"[success]Created {target}[/success]")


def switch_repository(session: SessionState, cli_state: CliState, raw_target: str, persistence: SessionPersistence) -> None:
    session.repo_path = resolve_navigation_target(raw_target, session.repo_path)
    session.conversation_history.clear()
    session.edit_history.clear()
    session.pending_approval = None
    cli_state.last_response = None
    clear_repo_summary(session.repo_path)
    persistence.save(session)
    console.print(f"[success]Repository updated to {session.repo_path}[/success]")
    if discover_instruction_files(session.repo_path):
        print_memory(session)


def prompt_approval(pending: PendingApproval, session: SessionState, persistence: SessionPersistence) -> bool:
    choice = Prompt.ask(
        Text("Approve this action? [y]es / [n]o / [a]lways", style="soft"),
        choices=["y", "n", "a"],
        default="n",
        console=console,
    )
    if choice == "a":
        if pending.approval_kind == "write":
            session.auto_approve_writes = True
        else:
            session.auto_approve_commands = True
        persistence.save(session)
        return True
    return choice == "y"


def parse_open_target(raw_value: str) -> tuple[str, int | None]:
    match = OPEN_PATTERN.fullmatch(raw_value.strip())
    if match is None:
        return raw_value.strip(), None
    line = match.group("line")
    return match.group("path").strip(), (int(line) if line else None)


def run_direct_tool(session: SessionState, settings: Settings, tool_name: str, arguments: dict[str, object]) -> str:
    tool = TOOL_REGISTRY[tool_name]
    return tool.handler(session.repo_path, settings, arguments)


def run_with_status_and_queue(
    action_label: str,
    action: Callable[[Callable[[dict[str, str]], None]], AgentRunResponse],
) -> tuple[AgentRunResponse, list[str]]:
    result: dict[str, AgentRunResponse | BaseException | None] = {"response": None, "error": None}
    queued_prompts: list[str] = []
    buffer: list[str] = []
    detail = {"text": ""}

    def on_event(event: dict[str, str]) -> None:
        detail["text"] = describe_event(event)

    def task() -> None:
        try:
            result["response"] = action(on_event)
        except BaseException as exc:  # pragma: no cover - passthrough for interactive runtime errors
            result["error"] = exc

    worker = threading.Thread(target=task, daemon=True)
    worker.start()

    with console.status(build_queue_status(action_label, buffer, queued_prompts, detail["text"])) as status:
        while worker.is_alive():
            while msvcrt.kbhit():
                apply_queue_key(buffer, queued_prompts, msvcrt.getwch())
            status.update(build_queue_status(action_label, buffer, queued_prompts, detail["text"]))
            sleep(0.05)

    worker.join()
    error = result["error"]
    if error is not None:
        raise error  # type: ignore[misc]
    response = result["response"]
    if response is None:  # pragma: no cover - defensive path
        raise RuntimeError("The agent run did not return a response.")
    return response, queued_prompts


def undo_last_edit(session: SessionState, persistence: SessionPersistence) -> None:
    if not session.edit_history:
        console.print("[muted]There is no edit to undo.[/muted]")
        return

    edit = session.edit_history[-1]
    preview = build_diff_preview(edit.path, edit.after_content, edit.before_content or "")
    console.print(
        Panel(
            Syntax(preview, "diff", line_numbers=False, word_wrap=True),
            title=f"Undo Preview · {edit.path}",
            border_style="warning",
        )
    )
    if not prompt_yes_no("Undo the last edit?", default=True):
        console.print("[muted]Cancelled.[/muted]")
        return

    message = restore_prepared_edit(session.repo_path, edit)
    session.edit_history.pop()
    clear_repo_summary(session.repo_path)
    persistence.save(session)
    console.print(f"[success]{message}[/success]")


def create_session_from_args(args: argparse.Namespace) -> SessionState:
    settings = get_settings()
    repo_input = args.repo_path or str(Path.cwd())
    model = args.model or settings.default_model
    repo_path = resolve_repo_path(repo_input)

    store = SessionStore()
    session = store.create_session(
        repo_path=repo_path,
        model=model,
        auto_approve_writes=args.auto_approve_writes,
        auto_approve_commands=args.auto_approve_commands,
    )
    apply_approval_mode(session, args.approval_mode)
    if args.auto_approve_writes or args.auto_approve_commands:
        session.auto_approve_writes = args.auto_approve_writes or session.auto_approve_writes
        session.auto_approve_commands = args.auto_approve_commands or session.auto_approve_commands
    return session


def prompt_for_session(args: argparse.Namespace) -> SessionState:
    settings = get_settings()
    repo_input = args.repo_path or prompt_text("Repository path", str(Path.cwd()))
    model = args.model or prompt_text("Ollama model", settings.default_model)
    repo_path = resolve_repo_path(repo_input)

    store = SessionStore()
    session = store.create_session(
        repo_path=repo_path,
        model=model,
        auto_approve_writes=False,
        auto_approve_commands=False,
    )

    if args.auto_approve_writes or args.auto_approve_commands:
        session.auto_approve_writes = args.auto_approve_writes
        session.auto_approve_commands = args.auto_approve_commands
        return session

    requested = prompt_text("Approval mode", args.approval_mode).lower()
    if requested not in {"ask", "auto-edit", "full-auto"}:
        requested = "ask"
    apply_approval_mode(session, requested)  # type: ignore[arg-type]
    return session


def bootstrap_session(args: argparse.Namespace, persistence: SessionPersistence) -> tuple[SessionState, bool]:
    session = prompt_for_session(args) if args.setup else create_session_from_args(args)
    restored = False
    if not args.fresh:
        previous = persistence.load_last()
        if previous is not None and previous.repo_path == session.repo_path:
            session = persistence.restore_into(session, previous, keep_explicit_model=bool(args.model))
            restored = True
    persistence.save(session)
    return session, restored


def handle_meta_command(
    command: str,
    session: SessionState,
    cli_state: CliState,
    settings: Settings,
    persistence: SessionPersistence,
) -> bool:
    parsed = parse_meta_command(command)
    if parsed is None:
        return False

    name, value = parsed
    if name in {"/exit", "/quit"}:
        raise SystemExit(0)
    if name == "/":
        print_command_matches("/")
        return True
    if name == "/help":
        print_help()
        return True
    if name in {"/status", "/session"}:
        print_status(session, cli_state)
        return True
    if name in {"/repo", "/cd"}:
        if not value:
            console.print(f"[soft]Current repository:[/soft] {session.repo_path}")
            return True
        switch_repository(session, cli_state, value, persistence)
        return True
    if name == "/diff":
        console.print(Panel(run_direct_tool(session, settings, "git_diff", {}), title="Git Diff", border_style="muted"))
        return True
    if name == "/git":
        console.print(Panel(run_direct_tool(session, settings, "git_status", {}), title="Git Status", border_style="muted"))
        return True
    if name == "/run-tests":
        console.print(Rule(style="dim"))
        console.print(Panel(run_direct_tool(session, settings, "run_tests", {}), title="Run Tests", border_style="info"))
        return True
    if name == "/steps":
        print_steps(cli_state)
        return True
    if name == "/verbose":
        if not value:
            console.print(f"[soft]Verbose mode:[/soft] {'on' if cli_state.show_steps else 'off'}")
            return True
        cli_state.show_steps = value.lower() in {"1", "on", "true", "yes"}
        console.print(f"[success]Verbose mode {'enabled' if cli_state.show_steps else 'disabled'}.[/success]")
        return True
    if name == "/memory":
        print_memory(session)
        return True
    if name == "/init":
        handle_init(session, persistence)
        return True
    if name == "/undo":
        undo_last_edit(session, persistence)
        return True
    if name == "/checkpoints":
        print_checkpoints(session)
        return True
    if name == "/history":
        print_history(session, value)
        return True
    if name in {"/clear", "/new"}:
        session.conversation_history.clear()
        session.pending_approval = None
        cli_state.last_response = None
        persistence.save(session)
        console.print("[success]Started a fresh chat in the current repository.[/success]")
        return True
    if name == "/model":
        if not value:
            console.print(f"[soft]Current model:[/soft] {session.model}")
            choose_model_interactively(session, settings, persistence)
            return True
        models = print_model_list(settings, session.model)
        if models and value not in models:
            console.print("[warning]That model is not currently installed locally. Setting it anyway.[/warning]")
        session.model = value
        persistence.save(session)
        console.print(f"[success]Model updated to {session.model}[/success]")
        return True
    if name == "/theme":
        if not value:
            console.print(f"[soft]Current theme:[/soft] {cli_state.theme_name}")
            return True
        try:
            cli_state.theme_name = normalize_theme_name(value)
        except ValueError as exc:
            console.print(f"[danger]{exc}[/danger]")
            return True
        set_active_theme(cli_state.theme_name)
        cli_state.prompt_session = build_prompt_session(cli_state.theme_name)
        console.print(f"[success]Theme updated to {cli_state.theme_name}[/success]")
        return True
    if name in {"/approvals", "/permissions"}:
        if not value:
            console.print(f"[soft]Current approval mode:[/soft] {get_approval_mode(session)}")
            return True
        mode = value.lower()
        if mode not in {"ask", "auto-edit", "full-auto"}:
            console.print("[danger]Approval mode must be one of: ask, auto-edit, full-auto[/danger]")
            return True
        apply_approval_mode(session, mode)  # type: ignore[arg-type]
        persistence.save(session)
        console.print(f"[success]Approval mode set to {mode}[/success]")
        return True
    if name == "/save":
        path = persistence.save(session)
        console.print(f"[success]Saved session to {path}[/success]")
        return True
    if name == "/open":
        if not value:
            console.print("[warning]Usage: /open PATH[:LINE][/warning]")
            return True
        path, line = parse_open_target(value)
        if line is None:
            content = run_direct_tool(session, settings, "read_file", {"path": path})
        else:
            content = run_direct_tool(session, settings, "open_file_at_line", {"path": path, "line": line, "context": 20})
        console.print(Panel(content, title=f"Open · {path}", border_style="muted"))
        return True
    if name == "/search":
        if not value:
            console.print("[warning]Usage: /search QUERY[/warning]")
            return True
        content = run_direct_tool(session, settings, "search_code", {"query": value})
        console.print(Panel(content, title=f"Search · {value}", border_style="muted"))
        return True
    if name == "/files":
        content = run_direct_tool(session, settings, "list_files", {"directory": value or "."})
        console.print(Panel(content, title="Files", border_style="muted"))
        return True

    console.print(f"[warning]Unknown command:[/warning] {name}")
    print_command_matches(name)
    return True


def handle_natural_navigation(
    command: str,
    session: SessionState,
    cli_state: CliState,
    persistence: SessionPersistence,
) -> bool:
    target = parse_natural_navigation(command)
    if target is None:
        return False
    try:
        switch_repository(session, cli_state, target, persistence)
    except ValueError as exc:
        console.print(Panel(str(exc), title="Navigation Error", border_style="danger"))
    return True


def handle_natural_shortcut(
    command: str,
    session: SessionState,
    settings: Settings,
    persistence: SessionPersistence,
) -> bool:
    lowered = command.strip().lower()
    if lowered in {"run tests", "test"}:
        console.print(Panel(run_direct_tool(session, settings, "run_tests", {}), title="Run Tests", border_style="info"))
        return True
    if lowered in {"show diff", "diff", "git diff"}:
        console.print(Panel(run_direct_tool(session, settings, "git_diff", {}), title="Git Diff", border_style="muted"))
        return True
    if lowered in {"git status", "status"}:
        console.print(Panel(run_direct_tool(session, settings, "git_status", {}), title="Git Status", border_style="muted"))
        return True
    if lowered in {"undo", "undo last edit"}:
        undo_last_edit(session, persistence)
        return True
    if lowered.startswith("open "):
        raw_target = command.strip()[5:].strip()
        path, line = parse_open_target(raw_target)
        if line is None:
            content = run_direct_tool(session, settings, "read_file", {"path": path})
        else:
            content = run_direct_tool(session, settings, "open_file_at_line", {"path": path, "line": line, "context": 20})
        console.print(Panel(content, title=f"Open · {path}", border_style="muted"))
        return True
    return False


def run_agent_once(
    agent: LocalCodingAgent,
    session: SessionState,
    cli_state: CliState,
    persistence: SessionPersistence,
    prompt: str,
) -> AgentRunResponse:
    response, queued_prompts = run_with_status_and_queue(
        "Thinking",
        lambda on_event: agent.run(session, prompt, on_event=on_event),
    )
    cli_state.last_response = response
    persistence.save(session)
    print_response(response, show_steps=cli_state.show_steps)

    while response.status == "needs_confirmation" and response.pending_approval is not None:
        approved = prompt_approval(response.pending_approval, session, persistence)
        response, more_queued = run_with_status_and_queue(
            "Continuing",
            lambda on_event: agent.resume_after_approval(session, approve=approved, on_event=on_event),
        )
        queued_prompts.extend(more_queued)
        cli_state.last_response = response
        persistence.save(session)
        print_response(response, show_steps=cli_state.show_steps)
    while queued_prompts:
        queued_prompt = queued_prompts.pop(0)
        console.print(Rule(style="dim"))
        console.print(f"[muted]Running queued message:[/muted] {clip_text(queued_prompt, 100)}")
        response = run_agent_once(agent, session, cli_state, persistence, queued_prompt)
    return response


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    persistence = SessionPersistence()
    agent = LocalCodingAgent(settings)
    theme_name = normalize_theme_name(args.theme)
    set_active_theme(theme_name)

    try:
        session, restored = bootstrap_session(args, persistence)
    except ValueError as exc:
        console.print(f"[danger]Session error:[/danger] {exc}")
        return 1
    except KeyboardInterrupt:
        console.print("\n[muted]Cancelled.[/muted]")
        return 1

    cli_state = CliState(
        show_steps=args.show_steps,
        restored_session=restored,
        theme_name=theme_name,
        prompt_session=build_prompt_session(theme_name),
    )
    print_welcome(session, cli_state)
    if discover_instruction_files(session.repo_path):
        console.print(f"[muted]Loaded memory:[/muted] {', '.join(path.name for path in discover_instruction_files(session.repo_path))}")

    if args.prompt:
        run_agent_once(agent, session, cli_state, persistence, " ".join(args.prompt))
        return 0

    while True:
        try:
            user_input = prompt_for_user_input(cli_state)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[muted]Exiting terminal mode.[/muted]")
            return 0

        if not user_input:
            continue
        if user_input == "/":
            print_command_matches("/")
            continue

        try:
            if handle_meta_command(user_input, session, cli_state, settings, persistence):
                continue
        except SystemExit:
            console.print("[muted]Exiting terminal mode.[/muted]")
            return 0

        if handle_natural_navigation(user_input, session, cli_state, persistence):
            continue

        if handle_natural_shortcut(user_input, session, settings, persistence):
            continue

        console.print(Rule(style="dim"))
        run_agent_once(agent, session, cli_state, persistence, user_input)


if __name__ == "__main__":
    raise SystemExit(main())
