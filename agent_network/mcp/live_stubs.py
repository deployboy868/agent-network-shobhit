"""Placeholders for real API clients — implement when mentor provides credentials."""

from __future__ import annotations

from typing import Optional

from typing import List

from agent_network.models import AgentActionResult, TaskReviewItem, Ticket
from agent_network.mcp.base import GitLabTools, JiraTools, TeamsTools, ToolSet, WorkdayTools


class _NotConfigured:
    def _fail(self, system: str) -> AgentActionResult:
        return AgentActionResult(
            success=False,
            detail=(
                f"{system} live mode not implemented. Set AGENT_NETWORK_MODE=mock "
                "or add API client code and credentials in .env"
            ),
        )


class LiveJiraStub(JiraTools, _NotConfigured):
    def create_ticket(self, title: str, description: str, reporter_id: str) -> Ticket:
        raise NotImplementedError(self._fail("Jira").detail)

    def assign_ticket(self, ticket_id: str, assignee_id: str) -> AgentActionResult:
        return self._fail("Jira")

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        return None

    def update_status(self, ticket_id: str, status: str) -> AgentActionResult:
        return self._fail("Jira")

    def list_tickets(
        self,
        assignee_email: Optional[str] = None,
        only_demo_tickets: bool = True,
    ) -> List[TaskReviewItem]:
        return []


class LiveGitLabStub(GitLabTools, _NotConfigured):
    def link_mr_to_ticket(self, ticket_id: str, mr_url: str) -> AgentActionResult:
        return self._fail("GitLab")


class LiveTeamsStub(TeamsTools, _NotConfigured):
    def notify_user(self, email: str, text: str) -> AgentActionResult:
        return self._fail("Teams")


class LiveWorkdayStub(WorkdayTools, _NotConfigured):
    def get_employee_manager(self, employee_id: str) -> AgentActionResult:
        return self._fail("Workday")


class LiveToolSetStub(ToolSet):
    def __init__(self) -> None:
        self.jira = LiveJiraStub()
        self.gitlab = LiveGitLabStub()
        self.teams = LiveTeamsStub()
        self.workday = LiveWorkdayStub()
