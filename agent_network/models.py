"""Shared data shapes for agents, tasks, and messages."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class Skill(str, Enum):
    """Skills map to which MCP-style tools an agent may use."""
    JIRA = "jira"
    GITLAB = "gitlab"
    TEAMS = "teams"
    WORKDAY = "workday"


class Employee(BaseModel):
    employee_id: str
    name: str
    email: str
    team: str
    skills: list[Skill] = Field(default_factory=list)
    is_absent: bool = False


class AbsenceWindow(BaseModel):
    """A scheduled period during which the employee is away."""

    start: datetime
    end: datetime
    note: str = ""

    def contains(self, when: datetime) -> bool:
        return self.start <= when <= self.end


class TwinStandInPolicy(BaseModel):
    """What the twin may do, and how it should behave, while the employee is absent."""

    can_delegate: bool = True
    notify_on_delegate: bool = True
    notify_on_colleague_help: bool = False
    require_ticket_approval: bool = False
    default_delegate_to: Optional[str] = None
    # Free-text directions from the owner: how the twin should act in their absence.
    instructions: str = ""
    # Scheduled away periods (owner-declared); used alongside Teams presence.
    absence_windows: list[AbsenceWindow] = Field(default_factory=list)


class Ticket(BaseModel):
    ticket_id: str = Field(default_factory=lambda: f"JIRA-{uuid4().hex[:8].upper()}")
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.OPEN
    assignee_id: Optional[str] = None
    reporter_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class AgentMessageType(str, Enum):
    TASK_ASSIGN = "task_assign"
    TASK_ACK = "task_ack"
    STATUS_REQUEST = "status_request"
    STATUS_UPDATE = "status_update"
    FOLLOW_UP = "follow_up"


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    sender_agent_id: str
    recipient_agent_id: str
    message_type: AgentMessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class AgentActionResult(BaseModel):
    success: bool
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)


class TaskReviewItem(BaseModel):
    ticket_id: str
    title: str
    status_label: str
    status: TaskStatus
    assignee_email: Optional[str] = None


class TaskReviewReport(BaseModel):
    """Agent-readable summary of tickets for manager 'review progress' demos."""
    items: list[TaskReviewItem] = Field(default_factory=list)
    total: int = 0
    open_count: int = 0
    in_progress_count: int = 0
    done_count: int = 0
    blocked_count: int = 0

    def summary_text(self) -> str:
        if self.total == 0:
            return "No matching tickets found."
        return (
            f"{self.total} ticket(s): "
            f"{self.open_count} open, {self.in_progress_count} in progress, "
            f"{self.done_count} done, {self.blocked_count} blocked."
        )
