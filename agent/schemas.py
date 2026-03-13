from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from tools.edit_operations import PreparedEdit


class CreateSessionRequest(BaseModel):
    repo_path: str
    model: str | None = None
    auto_approve_writes: bool = False
    auto_approve_commands: bool = False


class SessionResponse(BaseModel):
    session_id: str
    repo_path: str
    model: str
    auto_approve_writes: bool
    auto_approve_commands: bool
    has_pending_approval: bool


class RunAgentRequest(BaseModel):
    message: str = Field(min_length=1)


class ApprovalRequest(BaseModel):
    approval_id: str
    approve: bool


class ModelDecision(BaseModel):
    reasoning_summary: str = Field(description="Short explanation of why this step helps.")
    action: Literal["tool", "final"]
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    final_answer: str | None = None


class StepTrace(BaseModel):
    iteration: int
    reasoning_summary: str
    action: Literal["tool", "final", "approval"]
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    observation: str | None = None


class PendingApproval(BaseModel):
    approval_id: str
    tool_name: str
    tool_input: dict[str, Any]
    approval_kind: Literal["write", "command"]
    reason: str
    message: str
    preview: str | None = None


class AgentRunResponse(BaseModel):
    session_id: str
    status: Literal["completed", "needs_confirmation", "rejected", "error"]
    answer: str | None = None
    reasoning_summary: str | None = None
    steps: list[StepTrace] = Field(default_factory=list)
    pending_approval: PendingApproval | None = None
    git_diff: str | None = None
    error: str | None = None


@dataclass(slots=True)
class PendingApprovalState:
    approval_id: str
    tool_name: str
    tool_input: dict[str, Any]
    approval_kind: Literal["write", "command"]
    reason: str
    message: str
    preview: str | None
    prepared_edit: PreparedEdit | None
    loop_messages: list[dict[str, str]]
    steps: list[StepTrace]
    iteration: int
    user_message: str


@dataclass(slots=True)
class SessionState:
    repo_path: Path
    model: str
    auto_approve_writes: bool = False
    auto_approve_commands: bool = False
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    edit_history: list[PreparedEdit] = field(default_factory=list)
    pending_approval: PendingApprovalState | None = None
    session_id: str = field(default_factory=lambda: uuid4().hex[:12])
