from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from typing import Callable
from uuid import uuid4

from agent.cancellation import OperationCancelledError, raise_if_cancelled
from agent.config import Settings
from agent.ollama_client import OllamaJSONClient
from agent.project_docs import load_instruction_context
from agent.repo_awareness import build_repo_summary, clear_repo_summary
from agent.schemas import AgentRunResponse, PendingApproval, PendingApprovalState, SessionState, StepTrace
from tools.edit_operations import PreparedEdit, apply_prepared_edit, build_diff_preview
from tools.filesystem import preview_patch, preview_write
from tools.registry import TOOL_REGISTRY, render_tool_catalog
from tools.safety import check_command_safety
from tools.shell import run_command, run_tests


def _truncate(value: str, limit: int = 8000) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


class LocalCodingAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.llm = OllamaJSONClient(host=settings.ollama_host)

    def run(
        self,
        session: SessionState,
        user_message: str,
        on_event: Callable[[dict[str, str]], None] | None = None,
        cancel_event: Event | None = None,
    ) -> AgentRunResponse:
        loop_messages = [*session.conversation_history[-6:], {"role": "user", "content": user_message}]
        response = self._run_loop(
            session=session,
            loop_messages=loop_messages,
            steps=[],
            iteration_start=0,
            user_message=user_message,
            on_event=on_event,
            cancel_event=cancel_event,
        )
        if response.status == "completed" and response.answer:
            session.conversation_history.append({"role": "user", "content": user_message})
            session.conversation_history.append({"role": "assistant", "content": response.answer})
        return response

    def resume_after_approval(
        self,
        session: SessionState,
        approve: bool,
        on_event: Callable[[dict[str, str]], None] | None = None,
        cancel_event: Event | None = None,
    ) -> AgentRunResponse:
        pending = session.pending_approval
        if pending is None:
            return AgentRunResponse(
                session_id=session.session_id,
                status="error",
                error="There is no pending approval for this session.",
            )

        if not approve:
            steps = [
                *pending.steps,
                StepTrace(
                    iteration=pending.iteration,
                    reasoning_summary="User rejected the pending action.",
                    action="approval",
                    tool_name=pending.tool_name,
                    tool_input=pending.tool_input,
                    observation="Action rejected by user.",
                ),
            ]
            session.pending_approval = None
            return AgentRunResponse(
                session_id=session.session_id,
                status="rejected",
                answer="The pending action was not approved. Ask the agent to take a different approach.",
                reasoning_summary="Execution stopped because the pending action was rejected.",
                steps=steps,
                git_diff=self._safe_git_diff(session.repo_path),
            )

        try:
            raise_if_cancelled(cancel_event)
            if pending.prepared_edit is not None:
                tool_result = self._apply_prepared_edit(session, pending.prepared_edit)
            else:
                tool_result = self._execute_tool(
                    session=session,
                    tool_name=pending.tool_name,
                    tool_input=pending.tool_input,
                    ignore_confirmation=True,
                    cancel_event=cancel_event,
                )
        except OperationCancelledError:
            session.pending_approval = None
            return AgentRunResponse(
                session_id=session.session_id,
                status="rejected",
                answer="Cancelled.",
                reasoning_summary="Execution stopped because it was cancelled by the user.",
                steps=pending.steps,
                git_diff=self._safe_git_diff(session.repo_path),
            )
        except Exception as exc:
            session.pending_approval = None
            return AgentRunResponse(
                session_id=session.session_id,
                status="error",
                error=str(exc),
                steps=pending.steps,
            )

        approval_step = StepTrace(
            iteration=pending.iteration,
            reasoning_summary=pending.reason,
            action="approval",
            tool_name=pending.tool_name,
            tool_input=pending.tool_input,
            observation=_truncate(tool_result),
        )
        updated_messages = [
            *pending.loop_messages,
            {
                "role": "user",
                "content": (
                    f"Approved tool result for {pending.tool_name} with input "
                    f"{json.dumps(pending.tool_input, ensure_ascii=False)}:\n{tool_result}"
                ),
            },
        ]
        session.pending_approval = None
        response = self._run_loop(
            session=session,
            loop_messages=updated_messages,
            steps=[*pending.steps, approval_step],
            iteration_start=pending.iteration,
            user_message=pending.user_message,
            on_event=on_event,
            cancel_event=cancel_event,
        )
        if response.status == "completed" and response.answer:
            session.conversation_history.append({"role": "user", "content": pending.user_message})
            session.conversation_history.append({"role": "assistant", "content": response.answer})
        return response

    def _run_loop(
        self,
        *,
        session: SessionState,
        loop_messages: list[dict[str, str]],
        steps: list[StepTrace],
        iteration_start: int,
        user_message: str,
        on_event: Callable[[dict[str, str]], None] | None,
        cancel_event: Event | None,
    ) -> AgentRunResponse:
        for offset in range(self.settings.max_steps - iteration_start):
            if cancel_event is not None and cancel_event.is_set():
                return self._cancelled_response(session, steps)
            iteration = iteration_start + offset + 1
            decision = self.llm.decide(
                model=session.model,
                system_prompt=self._build_system_prompt(session.repo_path),
                messages=loop_messages,
            )
            if cancel_event is not None and cancel_event.is_set():
                return self._cancelled_response(session, steps)
            if on_event is not None:
                on_event(
                    {
                        "kind": "decision",
                        "iteration": str(iteration),
                        "action": decision.action,
                        "tool_name": decision.tool_name or "",
                    }
                )

            if decision.action == "final":
                final_answer = (decision.final_answer or "").strip()
                if not final_answer:
                    final_answer = (
                        decision.reasoning_summary.strip()
                        or (
                            "I could not complete that request with the available tools. "
                            "I can only work inside the configured repository root."
                        )
                    )
                final_step = StepTrace(
                    iteration=iteration,
                    reasoning_summary=decision.reasoning_summary,
                    action="final",
                    observation=final_answer,
                )
                return AgentRunResponse(
                    session_id=session.session_id,
                    status="completed",
                    answer=final_answer,
                    reasoning_summary=decision.reasoning_summary,
                    steps=[*steps, final_step],
                    git_diff=self._safe_git_diff(session.repo_path),
                )

            tool_name = decision.tool_name or ""
            tool_input = dict(decision.tool_input or {})
            step = StepTrace(
                iteration=iteration,
                reasoning_summary=decision.reasoning_summary,
                action="tool",
                tool_name=tool_name,
                tool_input=tool_input,
            )

            try:
                pending = self._maybe_build_pending(
                    session=session,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    reason=decision.reasoning_summary,
                    loop_messages=loop_messages,
                    steps=[*steps, step],
                    iteration=iteration,
                    user_message=user_message,
                )
                if pending is not None:
                    session.pending_approval = pending
                    return AgentRunResponse(
                        session_id=session.session_id,
                        status="needs_confirmation",
                        reasoning_summary=decision.reasoning_summary,
                        steps=[*steps, step],
                        pending_approval=PendingApproval(
                            approval_id=pending.approval_id,
                            tool_name=pending.tool_name,
                            tool_input=pending.tool_input,
                            approval_kind=pending.approval_kind,
                            reason=pending.reason,
                            message=pending.message,
                            preview=pending.preview,
                        ),
                        git_diff=self._safe_git_diff(session.repo_path),
                    )

                if on_event is not None:
                    on_event(
                        {
                            "kind": "tool_start",
                            "iteration": str(iteration),
                            "tool_name": tool_name,
                            "summary": decision.reasoning_summary,
                        }
                    )
                observation = self._execute_tool(
                    session=session,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    ignore_confirmation=False,
                    cancel_event=cancel_event,
                )
            except OperationCancelledError:
                return self._cancelled_response(session, [*steps, step])
            except Exception as exc:
                step.observation = f"Tool error: {exc}"
                return AgentRunResponse(
                    session_id=session.session_id,
                    status="error",
                    error=str(exc),
                    reasoning_summary=decision.reasoning_summary,
                    steps=[*steps, step],
                    git_diff=self._safe_git_diff(session.repo_path),
                )

            step.observation = _truncate(observation)
            if on_event is not None:
                on_event(
                    {
                        "kind": "tool_result",
                        "iteration": str(iteration),
                        "tool_name": tool_name,
                    }
                )
            steps = [*steps, step]
            loop_messages = [
                *loop_messages,
                {
                    "role": "assistant",
                    "content": (
                        f"Tool call: {tool_name}\n"
                        f"Reasoning summary: {decision.reasoning_summary}\n"
                        f"Arguments: {json.dumps(tool_input, ensure_ascii=False)}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Tool result for {tool_name}:\n{observation}",
                },
            ]

        return AgentRunResponse(
            session_id=session.session_id,
            status="error",
            error=f"Agent stopped after reaching max_steps={self.settings.max_steps}.",
            steps=steps,
            git_diff=self._safe_git_diff(session.repo_path),
        )

    def _maybe_build_pending(
        self,
        *,
        session: SessionState,
        tool_name: str,
        tool_input: dict[str, object],
        reason: str,
        loop_messages: list[dict[str, str]],
        steps: list[StepTrace],
        iteration: int,
        user_message: str,
    ) -> PendingApprovalState | None:
        tool = TOOL_REGISTRY.get(tool_name)
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        if tool.approval_kind == "write" and not session.auto_approve_writes:
            prepared_edit = self._prepare_edit(session.repo_path, tool_name, tool_input)
            return PendingApprovalState(
                approval_id=uuid4().hex[:12],
                tool_name=tool_name,
                tool_input=tool_input,
                approval_kind="write",
                reason=reason,
                message=f"{tool_name} modifies the repository and requires confirmation.",
                preview=build_diff_preview(
                    prepared_edit.path,
                    prepared_edit.before_content,
                    prepared_edit.after_content,
                ),
                prepared_edit=prepared_edit,
                loop_messages=loop_messages,
                steps=steps,
                iteration=iteration,
                user_message=user_message,
            )

        if tool.approval_kind == "command":
            safety = check_command_safety(str(tool_input.get("command", "")))
            if safety.requires_confirmation and not session.auto_approve_commands:
                return PendingApprovalState(
                    approval_id=uuid4().hex[:12],
                    tool_name=tool_name,
                    tool_input=tool_input,
                    approval_kind="command",
                    reason=reason,
                    message=safety.reason or "run_command requires confirmation.",
                    preview=str(tool_input.get("command", "")),
                    prepared_edit=None,
                    loop_messages=loop_messages,
                    steps=steps,
                    iteration=iteration,
                    user_message=user_message,
                )
        return None

    def _execute_tool(
        self,
        *,
        session: SessionState,
        tool_name: str,
        tool_input: dict[str, object],
        ignore_confirmation: bool,
        cancel_event: Event | None,
    ) -> str:
        raise_if_cancelled(cancel_event)
        tool = TOOL_REGISTRY.get(tool_name)
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        if tool_name in {"write_file", "apply_patch"}:
            prepared_edit = self._prepare_edit(session.repo_path, tool_name, tool_input)
            return self._apply_prepared_edit(session, prepared_edit)

        if tool_name == "run_tests":
            return run_tests(session.repo_path, self.settings.command_timeout_seconds, cancel_event=cancel_event)

        if tool_name == "run_command":
            command = str(tool_input.get("command", ""))
            safety = check_command_safety(command)
            return run_command(
                session.repo_path,
                safety.argv,
                timeout_seconds=self.settings.command_timeout_seconds,
                cancel_event=cancel_event,
            )

        if tool_name == "run_command" and ignore_confirmation:
            check_command_safety(str(tool_input.get("command", "")))

        return tool.handler(session.repo_path, self.settings, tool_input)

    def _prepare_edit(self, repo_path: Path, tool_name: str, tool_input: dict[str, object]) -> PreparedEdit:
        if tool_name == "write_file":
            return preview_write(
                repo_path,
                str(tool_input.get("path", "")),
                str(tool_input.get("content", "")),
            )
        if tool_name == "apply_patch":
            return preview_patch(
                repo_path,
                str(tool_input.get("path", "")),
                str(tool_input.get("search_text", "")),
                str(tool_input.get("replace_text", "")),
                replace_all=bool(tool_input.get("replace_all", False)),
                expected_occurrences=(
                    None
                    if tool_input.get("expected_occurrences") in (None, "")
                    else int(tool_input["expected_occurrences"])
                ),
            )
        raise ValueError(f"{tool_name} does not support prepared edits.")

    def _apply_prepared_edit(self, session: SessionState, prepared_edit: PreparedEdit) -> str:
        result = apply_prepared_edit(session.repo_path, prepared_edit)
        session.edit_history.append(prepared_edit)
        clear_repo_summary(session.repo_path)
        return result

    def _cancelled_response(self, session: SessionState, steps: list[StepTrace]) -> AgentRunResponse:
        return AgentRunResponse(
            session_id=session.session_id,
            status="rejected",
            answer="Cancelled.",
            reasoning_summary="Execution stopped because it was cancelled by the user.",
            steps=steps,
            git_diff=self._safe_git_diff(session.repo_path),
        )

    def _build_system_prompt(self, repo_path: Path) -> str:
        prompt = (
            "You are a local coding agent inspired by terminal coding assistants. "
            "Inspect the repository, answer questions, propose fixes, edit files when necessary, "
            "and run safe commands.\n\n"
            f"Repository root: {repo_path}\n\n"
            "Repository summary:\n"
            f"{build_repo_summary(str(repo_path))}\n\n"
            "Rules:\n"
            "- Only use the available tools.\n"
            "- Paths must remain inside the repository root.\n"
            "- If the user asks for a file or command outside the repository root, explain that limitation clearly in final_answer.\n"
            "- Read files and search code before changing anything.\n"
            "- Prefer apply_patch for focused edits to existing files.\n"
            "- Use write_file only when creating a file or deliberately replacing the full contents.\n"
            "- Keep reasoning_summary short and practical.\n"
            "- When you have enough information, return action='final'.\n"
            "- When action='final', always provide a direct final_answer for the user.\n\n"
            "Available tools:\n"
            f"{render_tool_catalog()}\n\n"
            "Return JSON matching this schema exactly:\n"
            "{ reasoning_summary: string, action: 'tool' | 'final', tool_name?: string, tool_input?: object, final_answer?: string }"
        )
        instruction_context = load_instruction_context(repo_path)
        if instruction_context:
            prompt += (
                "\n\nProject instruction files are loaded automatically. Follow them unless the user explicitly overrides them.\n\n"
                f"{instruction_context}"
            )
        return prompt

    def _safe_git_diff(self, repo_path: Path) -> str:
        try:
            return TOOL_REGISTRY["git_diff"].handler(repo_path, self.settings, {})
        except Exception as exc:
            return f"git_diff error: {exc}"
