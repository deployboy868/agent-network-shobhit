"""Digital twin: one agent per employee."""

from __future__ import annotations

import logging
from typing import Optional

from agent_network.bus import AgentMessageBus
from agent_network.models import (
    AgentActionResult,
    AgentMessage,
    AgentMessageType,
    Employee,
    Skill,
    TaskReviewReport,
    TaskStatus,
    Ticket,
)
from agent_network.config import is_demo_safe_mode, is_mock_mode, jira_email
from agent_network.mcp import ToolSet, get_toolset
from agent_network.registry import employee_display_name

logger = logging.getLogger(__name__)


class DigitalTwinAgent:
    """
    Represents one employee's agent.
    - Uses tools allowed by their skills (Jira, GitLab, Teams, Workday).
    - Sends/receives messages on the agent bus for coordination.
    """

    def __init__(
        self,
        employee: Employee,
        bus: AgentMessageBus,
        tools: Optional[ToolSet] = None,
    ) -> None:
        self.employee = employee
        self.agent_id = f"twin-{employee.employee_id}"
        self.bus = bus
        self.tools = tools or get_toolset()
        self._assigned_tickets: dict[str, Ticket] = {}
        bus.register(self.agent_id, self._on_message)

    def _has_skill(self, skill: Skill) -> bool:
        return skill in self.employee.skills

    def _on_message(self, message: AgentMessage) -> None:
        if message.message_type == AgentMessageType.TASK_ASSIGN:
            self._handle_task_assign(message)
        elif message.message_type == AgentMessageType.STATUS_REQUEST:
            self._handle_status_request(message)

    def create_and_delegate_ticket(
        self,
        title: str,
        description: str,
        assignee_employee_id: str,
    ) -> AgentActionResult:
        """Demo flow: reporter twin creates Jira ticket and asks assignee's twin."""
        if not self._has_skill(Skill.JIRA):
            return AgentActionResult(success=False, detail="This agent lacks Jira skill")

        ticket = self.tools.jira.create_ticket(
            title=title,
            description=description,
            reporter_id=self.employee.employee_id,
        )
        assign_msg = AgentMessage(
            sender_agent_id=self.agent_id,
            recipient_agent_id=f"twin-{assignee_employee_id}",
            message_type=AgentMessageType.TASK_ASSIGN,
            payload={
                "ticket_id": ticket.ticket_id,
                "title": ticket.title,
                "description": ticket.description,
            },
        )
        self.bus.send(assign_msg)
        logger.info(
            "[%s] delegated %s to %s (agent bus)",
            self.agent_id,
            ticket.ticket_id,
            employee_display_name(assignee_employee_id),
        )
        return AgentActionResult(
            success=True,
            detail="Ticket created and assignment sent to peer agent",
            data={"ticket_id": ticket.ticket_id},
        )

    def _handle_task_assign(self, message: AgentMessage) -> None:
        if not self._has_skill(Skill.JIRA):
            self.bus.send(
                AgentMessage(
                    sender_agent_id=self.agent_id,
                    recipient_agent_id=message.sender_agent_id,
                    message_type=AgentMessageType.TASK_ACK,
                    payload={"accepted": False, "reason": "No Jira skill"},
                )
            )
            return

        ticket_id = message.payload["ticket_id"]
        result = self.tools.jira.assign_ticket(ticket_id, self.employee.employee_id)
        ticket = self.tools.jira.get_ticket(ticket_id)
        if ticket:
            self._assigned_tickets[ticket_id] = ticket

        if self._has_skill(Skill.TEAMS) and not is_demo_safe_mode():
            self.tools.teams.notify_user(
                self.employee.email,
                f"You were assigned ticket {ticket_id}: {message.payload.get('title', '')}",
            )

        self.bus.send(
            AgentMessage(
                sender_agent_id=self.agent_id,
                recipient_agent_id=message.sender_agent_id,
                message_type=AgentMessageType.TASK_ACK,
                payload={"accepted": result.success, "ticket_id": ticket_id},
            )
        )

    def _handle_status_request(self, message: AgentMessage) -> None:
        ticket_id = message.payload.get("ticket_id")
        ticket = self.tools.jira.get_ticket(ticket_id) if ticket_id else None
        status = ticket.status.value if ticket else "unknown"
        self.bus.send(
            AgentMessage(
                sender_agent_id=self.agent_id,
                recipient_agent_id=message.sender_agent_id,
                message_type=AgentMessageType.STATUS_UPDATE,
                payload={"ticket_id": ticket_id, "status": status},
            )
        )

    def mark_ticket_done(self, ticket_id: str) -> AgentActionResult:
        """Assignee completes work — updates Jira (mock) and notifies reporter via bus."""
        if not self._has_skill(Skill.JIRA):
            return AgentActionResult(success=False, detail="No Jira skill")
        result = self.tools.jira.update_status(ticket_id, TaskStatus.DONE.value)
        return result

    def request_status_from(self, assignee_employee_id: str, ticket_id: str) -> None:
        self.bus.send(
            AgentMessage(
                sender_agent_id=self.agent_id,
                recipient_agent_id=f"twin-{assignee_employee_id}",
                message_type=AgentMessageType.STATUS_REQUEST,
                payload={"ticket_id": ticket_id},
            )
        )

    def follow_up_until_done(
        self,
        ticket_id: str,
        assignee_employee_id: str,
        max_checks: int = 5,
    ) -> TaskStatus:
        """
        Autonomous follow-up: ask assignee's twin for status until ticket is done.
        In mock mode, the shared Jira store is updated when the assignee twin handles messages.
        """
        assignee_agent_id = f"twin-{assignee_employee_id}"
        for _ in range(max_checks):
            self.request_status_from(assignee_employee_id, ticket_id)
            inbox = self.bus.inbox_for(self.agent_id)
            updates = [
                m
                for m in inbox
                if m.message_type == AgentMessageType.STATUS_UPDATE
                and m.sender_agent_id == assignee_agent_id
                and m.payload.get("ticket_id") == ticket_id
            ]
            if updates:
                status = updates[-1].payload.get("status", TaskStatus.OPEN.value)
                if status == TaskStatus.DONE.value:
                    return TaskStatus.DONE
            ticket = self.tools.jira.get_ticket(ticket_id)
            if ticket and ticket.status == TaskStatus.DONE:
                return TaskStatus.DONE
        ticket = self.tools.jira.get_ticket(ticket_id)
        return ticket.status if ticket else TaskStatus.OPEN

    def review_tasks(self, assignee_email: Optional[str] = None) -> TaskReviewReport:
        """
        Fetch and summarize tickets (read-only). Answers manager 'review progress' ask.
        Live mode: only [Agent-Network-TEST] tickets in configured project.
        """
        if not self._has_skill(Skill.JIRA):
            return TaskReviewReport()

        email = assignee_email
        if not email and not is_mock_mode() and is_demo_safe_mode():
            email = jira_email()

        items = self.tools.jira.list_tickets(
            assignee_email=email,
            only_demo_tickets=not is_mock_mode(),
        )
        report = TaskReviewReport(items=items, total=len(items))
        for item in items:
            if item.status == TaskStatus.OPEN:
                report.open_count += 1
            elif item.status == TaskStatus.IN_PROGRESS:
                report.in_progress_count += 1
            elif item.status == TaskStatus.DONE:
                report.done_count += 1
            elif item.status == TaskStatus.BLOCKED:
                report.blocked_count += 1
        return report
