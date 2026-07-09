"""In-memory fake Jira / GitLab / Teams / Workday for demos without API keys."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from agent_network.models import AgentActionResult, TaskReviewItem, TaskStatus, Ticket
from agent_network.mcp.base import GitLabTools, JiraTools, TeamsTools, ToolSet, WorkdayTools
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_INTERN_ID, DEMO_MANAGER_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MockJira(JiraTools):
    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._comments: dict[str, list[dict[str, str]]] = {}
        self._seed_demo_tickets()

    def _seed_demo_tickets(self) -> None:
        """Starter tickets so mock demos (talk_to_twin, review_tasks) are not empty."""
        samples = [
            (
                "[Agent-Network-TEST] Fix onboarding doc typo",
                "Update intern handbook section on MCP setup.",
                DEMO_MANAGER_ID,
                DEMO_ASSIGNEE_ID,
                TaskStatus.IN_PROGRESS,
            ),
            (
                "[Agent-Network-TEST] Review agent bus protocol",
                "Sample open ticket for list/get demos.",
                DEMO_MANAGER_ID,
                DEMO_ASSIGNEE_ID,
                TaskStatus.OPEN,
            ),
            (
                "[Agent-Network-TEST] Intern blocker on MCP setup",
                "Ticket assigned to intern for 'my tickets' demo.",
                DEMO_MANAGER_ID,
                DEMO_INTERN_ID,
                TaskStatus.OPEN,
            ),
        ]
        for title, description, reporter_id, assignee_id, status in samples:
            ticket = Ticket(
                title=title,
                description=description,
                reporter_id=reporter_id,
                assignee_id=assignee_id,
                status=status,
            )
            self._tickets[ticket.ticket_id] = ticket
        first_id = next(iter(self._tickets), None)
        if first_id:
            self._comments[first_id] = [
                {
                    "author": "Demo Manager",
                    "created": "2026-06-01",
                    "text": "Sample comment for status lookup demo.",
                }
            ]

    def create_ticket(self, title: str, description: str, reporter_id: str) -> Ticket:
        ticket = Ticket(title=title, description=description, reporter_id=reporter_id)
        self._tickets[ticket.ticket_id] = ticket
        return ticket

    def assign_ticket(self, ticket_id: str, assignee_id: str) -> AgentActionResult:
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            return AgentActionResult(success=False, detail=f"Ticket {ticket_id} not found")
        ticket.assignee_id = assignee_id
        ticket.status = TaskStatus.IN_PROGRESS
        ticket.updated_at = _now()
        return AgentActionResult(
            success=True,
            detail=f"Assigned {ticket_id} to {assignee_id}",
            data={"ticket_id": ticket_id, "assignee_id": assignee_id},
        )

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        return self._tickets.get(ticket_id)

    def list_comments(self, ticket_id: str, limit: int = 15) -> list[dict[str, str]]:
        comments = self._comments.get(ticket_id, [])
        return comments[:limit]

    def add_comment(self, ticket_id: str, text: str) -> AgentActionResult:
        if ticket_id not in self._tickets:
            return AgentActionResult(success=False, detail=f"Ticket {ticket_id} not found")
        self._comments.setdefault(ticket_id, []).append(
            {
                "author": "Agent Network",
                "created": _now().date().isoformat(),
                "text": text,
            }
        )
        return AgentActionResult(
            success=True,
            detail=f"Comment added to {ticket_id}",
            data={"ticket_id": ticket_id},
        )

    def update_status(self, ticket_id: str, status: str) -> AgentActionResult:
        ticket = self._tickets.get(ticket_id)
        if not ticket:
            return AgentActionResult(success=False, detail=f"Ticket {ticket_id} not found")
        try:
            ticket.status = TaskStatus(status)
        except ValueError:
            return AgentActionResult(success=False, detail=f"Invalid status: {status}")
        ticket.updated_at = _now()
        return AgentActionResult(success=True, detail="Status updated", data={"status": status})

    def list_tickets(
        self,
        assignee_email: Optional[str] = None,
        only_demo_tickets: bool = True,
    ) -> list[TaskReviewItem]:
        from agent_network.registry import employee_by_id

        items: list[TaskReviewItem] = []
        for ticket in self._tickets.values():
            if only_demo_tickets and not ticket.title.startswith("["):
                continue
            assignee_email_resolved: Optional[str] = None
            if ticket.assignee_id:
                emp = employee_by_id(ticket.assignee_id)
                assignee_email_resolved = emp.email if emp else ticket.assignee_id
            if assignee_email and assignee_email_resolved != assignee_email:
                continue
            items.append(
                TaskReviewItem(
                    ticket_id=ticket.ticket_id,
                    title=ticket.title,
                    status_label=ticket.status.value,
                    status=ticket.status,
                    assignee_email=assignee_email_resolved,
                )
            )
        return items


class MockGitLab(GitLabTools):
    def __init__(self) -> None:
        self._merge_requests = [
            {
                "iid": 42,
                "title": "[Agent-Network-TEST] Add twin stand-in policy",
                "web_url": "https://gitlab.example.com/demo/project/-/merge_requests/42",
                "state": "opened",
            },
            {
                "iid": 38,
                "title": "[Agent-Network-TEST] Wire GitLab into twin chat",
                "web_url": "https://gitlab.example.com/demo/project/-/merge_requests/38",
                "state": "opened",
            },
        ]

    def list_merge_requests(
        self, state: str = "opened", limit: int = 10
    ) -> list[dict[str, str | int]]:
        items = self._merge_requests
        if state != "all":
            items = [mr for mr in items if mr.get("state") == state]
        return items[:limit]

    def link_mr_to_ticket(self, ticket_id: str, mr_url: str) -> AgentActionResult:
        return AgentActionResult(
            success=True,
            detail="Linked MR (mock)",
            data={"ticket_id": ticket_id, "mr_url": mr_url},
        )

    def create_mr_from_ticket(
        self,
        ticket_id: str,
        title: str,
        description: str = "",
    ) -> AgentActionResult:
        iid = max((mr.get("iid", 0) for mr in self._merge_requests), default=41) + 1
        mr_url = f"https://gitlab.example.com/demo/project/-/merge_requests/{iid}"
        self._merge_requests.append(
            {
                "iid": iid,
                "title": title[:80],
                "web_url": mr_url,
                "state": "opened",
            }
        )
        return AgentActionResult(
            success=True,
            detail=f"Opened GitLab MR and linked to {ticket_id}: {mr_url} (mock)",
            data={
                "ticket_id": ticket_id,
                "mr_url": mr_url,
                "mr_iid": iid,
                "branch": f"agent-network/{ticket_id.lower()}",
                "file_path": f"docs/agent-network-tasks/{ticket_id}.md",
            },
        )


class MockTeams(TeamsTools):
    _notifications: list[dict[str, str]] = []

    def notify_user(self, email: str, text: str) -> AgentActionResult:
        self._notifications.append({"email": email, "text": text})
        return AgentActionResult(success=True, detail="Teams message sent (mock)")

    @classmethod
    def get_notifications(cls, email: str | None = None) -> list[dict[str, str]]:
        if email:
            return [n for n in cls._notifications if n["email"] == email]
        return list(cls._notifications)

    @classmethod
    def clear_notifications(cls) -> None:
        cls._notifications.clear()


class MockWorkday(WorkdayTools):
    def get_employee_manager(self, employee_id: str) -> AgentActionResult:
        emp = employee_by_id(employee_id)
        if not emp:
            return AgentActionResult(success=False, detail="Employee not found in mock roster")
        # Demo: pretend manager is the manager-role twin for everyone else
        manager_id = DEMO_MANAGER_ID if employee_id != DEMO_MANAGER_ID else DEMO_ASSIGNEE_ID
        return AgentActionResult(
            success=True,
            detail="Manager lookup (mock)",
            data={"employee_id": employee_id, "manager_id": manager_id},
        )


class MockToolSet(ToolSet):
    def __init__(self) -> None:
        self.jira = MockJira()
        self.gitlab = MockGitLab()
        self.teams = MockTeams()
        self.workday = MockWorkday()
