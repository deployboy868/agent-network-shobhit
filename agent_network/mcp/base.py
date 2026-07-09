"""Abstract tool interfaces matching project integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from agent_network.models import AgentActionResult, TaskReviewItem, Ticket


class JiraTools(ABC):
    @abstractmethod
    def create_ticket(self, title: str, description: str, reporter_id: str) -> Ticket:
        ...

    @abstractmethod
    def assign_ticket(self, ticket_id: str, assignee_id: str) -> AgentActionResult:
        ...

    @abstractmethod
    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        ...

    @abstractmethod
    def update_status(self, ticket_id: str, status: str) -> AgentActionResult:
        ...

    @abstractmethod
    def list_tickets(
        self,
        assignee_email: Optional[str] = None,
        only_demo_tickets: bool = True,
    ) -> list[TaskReviewItem]:
        """Read-only search. Live mode filters to safe-prefix demo tickets by default."""
        ...


class GitLabTools(ABC):
    @abstractmethod
    def link_mr_to_ticket(self, ticket_id: str, mr_url: str) -> AgentActionResult:
        ...


class TeamsTools(ABC):
    @abstractmethod
    def notify_user(self, email: str, text: str) -> AgentActionResult:
        ...


class WorkdayTools(ABC):
    @abstractmethod
    def get_employee_manager(self, employee_id: str) -> AgentActionResult:
        ...


class ToolSet(ABC):
    jira: JiraTools
    gitlab: GitLabTools
    teams: TeamsTools
    workday: WorkdayTools
