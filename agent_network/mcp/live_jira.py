"""Jira Cloud REST API client (email + API token)."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from agent_network import config
from agent_network.models import AgentActionResult, TaskReviewItem, TaskStatus, Ticket
from agent_network.mcp.base import JiraTools
from agent_network.registry import employee_by_id

logger = logging.getLogger(__name__)


def _adf_paragraph(text: str) -> dict[str, Any]:
    """Atlassian Document Format — required for Jira Cloud v3 description."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text or "(no description)"}],
            }
        ],
    }


def _adf_to_plain_text(node: Any) -> str:
    """Best-effort plain text from Atlassian Document Format."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return str(node.get("text", ""))
    parts: list[str] = []
    for child in node.get("content") or []:
        part = _adf_to_plain_text(child)
        if part:
            parts.append(part)
        if isinstance(child, dict) and child.get("type") == "paragraph":
            parts.append("\n")
    return "".join(parts).strip()


def _map_jira_status(status_name: str, status_category: str) -> TaskStatus:
    """Map Jira status to our simple enum."""
    key = (status_category or "").lower()
    if key == "done":
        return TaskStatus.DONE
    if key in ("indeterminate", "in_progress", "in progress"):
        return TaskStatus.IN_PROGRESS
    name = (status_name or "").lower()
    if "done" in name or "closed" in name or "resolved" in name:
        return TaskStatus.DONE
    if "progress" in name or "review" in name:
        return TaskStatus.IN_PROGRESS
    if "block" in name:
        return TaskStatus.BLOCKED
    return TaskStatus.OPEN


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


# LST workflow (forward-only). Shortcut: In Progress -> In Review (skip Need Review).
# Full path can include Need Review, but we never step backward (e.g. Stop Progress).
_WORKFLOW_STATUS_ORDER = (
    "need review",
    "in progress",
    "in review",
    "closed",
    "done",
    "resolved",
)


def _status_index(status_name: str) -> int:
    n = _normalize(status_name)
    for i, token in enumerate(_WORKFLOW_STATUS_ORDER):
        if token in n:
            return i
    return -1


class LiveJira(JiraTools):
    """Uses Jira REST API v3 with Basic auth (email + API token)."""

    def __init__(self) -> None:
        self._base = config.jira_base_url()
        self._auth_header = "Basic " + base64.b64encode(
            f"{config.jira_email()}:{config.jira_api_token()}".encode()
        ).decode()
        self._safe_prefix = config.jira_safe_prefix()
        self._allowed_project = config.jira_project_key_required()
        # Issue keys created by this process in the current run (extra safety).
        self._created_by_agent: set[str] = set()

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        data = None
        headers = {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            err_body = e.read().decode() if e.fp else ""
            logger.error("Jira HTTP %s: %s", e.code, err_body)
            raise RuntimeError(f"Jira API error {e.code}: {err_body}") from e

    def _apply_safe_prefix(self, title: str) -> str:
        if self._safe_prefix and not title.strip().startswith(self._safe_prefix):
            return f"{self._safe_prefix} {title.strip()}"
        return title.strip()

    def _fetch_issue_raw(self, ticket_id: str) -> dict[str, Any]:
        return self._request("GET", f"/rest/api/3/issue/{ticket_id}")

    def _assert_safe_to_modify(self, ticket_id: str) -> AgentActionResult | None:
        """
        Refuse to assign/close issues we did not create.
        Protects existing tickets in inactive/legacy projects.
        """
        if ticket_id in self._created_by_agent:
            return None
        try:
            issue = self._fetch_issue_raw(ticket_id)
        except RuntimeError as e:
            return AgentActionResult(success=False, detail=str(e))

        fields = issue.get("fields", {})
        project_key = (fields.get("project") or {}).get("key", "")
        if project_key != self._allowed_project:
            return AgentActionResult(
                success=False,
                detail=(
                    f"Blocked: {ticket_id} is in project {project_key}, not "
                    f"{self._allowed_project}. Will not modify."
                ),
            )
        summary = fields.get("summary", "")
        if self._safe_prefix and self._safe_prefix not in summary:
            return AgentActionResult(
                success=False,
                detail=(
                    f"Blocked: {ticket_id} does not have safe prefix "
                    f"'{self._safe_prefix}' in summary. Will not modify existing tickets."
                ),
            )
        return None

    def create_ticket(self, title: str, description: str, reporter_id: str) -> Ticket:
        safe_title = self._apply_safe_prefix(title)
        safe_description = (
            f"{description}\n\n---\nCreated by Agent Social Network internship demo. "
            f"Safe to delete. Prefix: {self._safe_prefix}"
        ).strip()
        payload = {
            "fields": {
                "project": {"key": config.jira_project_key()},
                "summary": safe_title,
                "description": _adf_paragraph(safe_description),
                "issuetype": {"name": config.jira_issue_type()},
            }
        }
        result = self._request("POST", "/rest/api/3/issue", payload)
        issue_key = result["key"]
        self._created_by_agent.add(issue_key)
        ticket = Ticket(
            ticket_id=issue_key,
            title=safe_title,
            description=safe_description,
            reporter_id=reporter_id,
            status=TaskStatus.OPEN,
        )
        logger.info("Created Jira issue %s (new test ticket only)", issue_key)
        return ticket

    def _issue_to_ticket(self, issue: dict[str, Any]) -> Ticket:
        fields = issue.get("fields", {})
        status = fields.get("status", {})
        category = status.get("statusCategory", {}).get("key", "")
        assignee = fields.get("assignee")
        assignee_id = assignee.get("accountId") if assignee else None
        description = _adf_to_plain_text(fields.get("description"))
        return Ticket(
            ticket_id=issue["key"],
            title=fields.get("summary", ""),
            description=description,
            status=_map_jira_status(status.get("name", ""), category),
            assignee_id=assignee_id,
            reporter_id=None,
        )

    def get_ticket(self, ticket_id: str) -> Optional[Ticket]:
        try:
            issue = self._fetch_issue_raw(ticket_id)
            return self._issue_to_ticket(issue)
        except RuntimeError:
            return None

    def list_comments(self, ticket_id: str, limit: int = 15) -> list[dict[str, str]]:
        """Read-only Jira comments for status lookups."""
        try:
            data = self._request(
                "GET",
                f"/rest/api/3/issue/{quote(ticket_id)}/comment?maxResults={limit}",
            )
        except RuntimeError as e:
            logger.warning("Could not list comments for %s: %s", ticket_id, e)
            return []
        items: list[dict[str, str]] = []
        for comment in data.get("comments") or []:
            if not isinstance(comment, dict):
                continue
            author = (comment.get("author") or {}).get("displayName") or "unknown"
            created = str(comment.get("created") or "")[:10]
            text = _adf_to_plain_text(comment.get("body"))
            if not text:
                continue
            items.append({"author": author, "created": created, "text": text})
        return items

    def _account_id_for_email(self, email: str) -> Optional[str]:
        project = config.jira_project_key()
        path = (
            f"/rest/api/3/user/assignable/search?project={quote(project)}"
            f"&query={quote(email)}"
        )
        users = self._request("GET", path)
        if isinstance(users, list) and users:
            return users[0].get("accountId")
        return None

    def _account_id_for_employee(self, assignee_id: str) -> Optional[str]:
        emp = employee_by_id(assignee_id)
        if not emp:
            return None
        return self._account_id_for_email(emp.email)

    def assign_ticket(self, ticket_id: str, assignee_id: str) -> AgentActionResult:
        blocked = self._assert_safe_to_modify(ticket_id)
        if blocked:
            return blocked
        if config.is_demo_safe_mode():
            demo_email = config.jira_email()
            account_id = self._account_id_for_email(demo_email)
            if not account_id:
                return AgentActionResult(
                    success=False,
                    detail=(
                        f"Demo safe mode: could not find Jira user for {demo_email}. "
                        "Check JIRA_EMAIL in .env matches your Atlassian account."
                    ),
                )
            logger.info(
                "Demo safe mode: assigning %s to you (%s) only",
                ticket_id,
                demo_email,
            )
            self._request(
                "PUT",
                f"/rest/api/3/issue/{ticket_id}/assignee",
                {"accountId": account_id},
            )
            return AgentActionResult(
                success=True,
                detail=f"Demo safe mode: assigned to you ({demo_email})",
                data={
                    "ticket_id": ticket_id,
                    "demo_safe_mode": True,
                    "assignee_email": demo_email,
                },
            )
        account_id = self._account_id_for_employee(assignee_id)
        if not account_id:
            return AgentActionResult(
                success=False,
                detail=(
                    f"Could not find Jira user for {assignee_id}. "
                    "Check employee email in registry.py matches Jira."
                ),
            )
        self._request(
            "PUT",
            f"/rest/api/3/issue/{ticket_id}/assignee",
            {"accountId": account_id},
        )
        return AgentActionResult(
            success=True,
            detail=f"Assigned {ticket_id} in Jira",
            data={"ticket_id": ticket_id, "assignee_account_id": account_id},
        )

    def _list_transitions(self, ticket_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/rest/api/3/issue/{ticket_id}/transitions")
        return data.get("transitions", [])

    def _transition_id_for_done(self, ticket_id: str) -> Optional[str]:
        transitions = self._list_transitions(ticket_id)
        configured = config.jira_done_transition()
        if configured:
            for t in transitions:
                if (t.get("name") or "").lower() == configured.lower():
                    return t.get("id")

        done_names = (
            "done",
            "close",
            "closed",  # LST final button is "CLOSED"
            "resolve",
            "resolved",
            "complete",
            "completed",
            "finish",
            "finished",
            "shut",
            "archive",
            "pass",
            "accept",
            "fixed",
            "cancel",
            "cancelled",
            "won't do",
            "wont do",
            "decline",
            "reject",
        )
        for t in transitions:
            name = (t.get("name") or "").lower()
            to_cat = (t.get("to", {}).get("statusCategory", {}).get("key") or "").lower()
            if name in done_names or to_cat == "done":
                return t.get("id")
        return None

    def available_transition_names(self, ticket_id: str) -> list[str]:
        return [t.get("name", "?") for t in self._list_transitions(ticket_id)]

    def describe_transitions(self, ticket_id: str) -> list[str]:
        """Human-readable lines: 'Button name' -> Status (category)."""
        lines: list[str] = []
        for t in self._list_transitions(ticket_id):
            to_status = t.get("to", {})
            to_name = to_status.get("name", "?")
            to_cat = to_status.get("statusCategory", {}).get("name", "?")
            lines.append(f"{t.get('name', '?')} -> {to_name} ({to_cat})")
        return lines

    def _apply_transition_by_name(self, ticket_id: str, name: str) -> bool:
        for t in self._list_transitions(ticket_id):
            if (t.get("name") or "").lower() == name.lower():
                self._request(
                    "POST",
                    f"/rest/api/3/issue/{ticket_id}/transitions",
                    {"transition": {"id": t.get("id")}},
                )
                return True
        return False

    def _current_status_name(self, ticket_id: str) -> str:
        issue = self._fetch_issue_raw(ticket_id)
        return issue.get("fields", {}).get("status", {}).get("name", "")

    def _is_closed_status(self, ticket_id: str) -> bool:
        issue = self._fetch_issue_raw(ticket_id)
        status = issue.get("fields", {}).get("status", {})
        category = status.get("statusCategory", {}).get("key", "")
        name = _normalize(status.get("name", ""))
        return category == "done" or "closed" in name or "resolved" in name

    def _find_transition_for_step(
        self, transitions: list[dict[str, Any]], step: str, current: str
    ) -> Optional[dict[str, Any]]:
        """Match workflow step to button name or destination; skip no-op transitions."""
        step_n = _normalize(step)
        current_n = _normalize(current)
        for t in transitions:
            btn = _normalize(t.get("name", ""))
            dest = _normalize((t.get("to") or {}).get("name", ""))
            if dest == current_n:
                continue
            if btn == step_n or dest == step_n:
                return t
        return None

    def _pick_forward_transition(
        self, transitions: list[dict[str, Any]], current_status: str
    ) -> Optional[dict[str, Any]]:
        """
        Pick the nearest forward transition (LST UI).
        In Progress -> IN REVIEW (skip NEED REVIEW). In Review -> CLOSED.
        """
        current_idx = _status_index(current_status)
        current_n = _normalize(current_status)

        if "in review" in current_n:
            for t in transitions:
                btn = _normalize(t.get("name", ""))
                dest = _normalize((t.get("to") or {}).get("name", ""))
                if btn == "closed" or dest == "closed":
                    return t

        best: Optional[tuple[int, dict[str, Any]]] = None
        for t in transitions:
            dest_name = (t.get("to") or {}).get("name", "")
            dest_n = _normalize(dest_name)
            if dest_n == current_n:
                continue
            dest_idx = _status_index(dest_name)
            if dest_idx <= current_idx:
                continue
            if "in progress" in current_n and "need review" in dest_n:
                continue
            if "in progress" in current_n and "in review" in dest_n:
                return t
            if best is None or dest_idx < best[0]:
                best = (dest_idx, t)
        return best[1] if best else None

    def _walk_workflow_to_closed(self, ticket_id: str) -> AgentActionResult:
        """
        Walk LST-style workflow forward until Closed/Done.
        Need Review -> In Progress -> In Review -> Closed
        """
        steps = config.jira_close_workflow()
        if not steps:
            return AgentActionResult(
                success=False,
                detail="No JIRA_CLOSE_WORKFLOW configured in .env",
            )

        applied: list[str] = []
        last_buttons: list[str] = []

        for _ in range(8):
            if self._is_closed_status(ticket_id):
                path = " -> ".join(applied) if applied else "(already closed)"
                return AgentActionResult(
                    success=True,
                    detail=f"Workflow complete: {path}",
                    data={"steps_applied": applied},
                )

            current_status = self._current_status_name(ticket_id)
            transitions = self._list_transitions(ticket_id)
            match = self._pick_forward_transition(transitions, current_status)

            if not match:
                for step in steps:
                    match = self._find_transition_for_step(
                        transitions, step, current_status
                    )
                    if match:
                        break

            if not match:
                break

            btn = match.get("name", "?")
            if last_buttons and last_buttons[-3:] == [btn, btn, btn]:
                break

            self._request(
                "POST",
                f"/rest/api/3/issue/{ticket_id}/transitions",
                {"transition": {"id": match.get("id")}},
            )
            applied.append(btn)
            last_buttons.append(btn)

        details = self.describe_transitions(ticket_id)
        hint = "; ".join(details) if details else "(none)"
        return AgentActionResult(
            success=False,
            detail=(
                f"Workflow stuck at '{self._current_status_name(ticket_id)}'. "
                f"Applied: {applied or 'none'}. Available now: {hint}. "
                f"Run: python -m agent_network.demo.discover_jira_transitions {ticket_id}"
            ),
        )

    def update_status(self, ticket_id: str, status: str) -> AgentActionResult:
        blocked = self._assert_safe_to_modify(ticket_id)
        if blocked:
            return blocked
        if status != TaskStatus.DONE.value:
            return AgentActionResult(
                success=False,
                detail=(
                    f"Live Jira MVP only supports marking done (got {status}). "
                    "Ask mentor for other transition names if needed."
                ),
            )

        if config.jira_close_workflow():
            return self._walk_workflow_to_closed(ticket_id)

        transition_id = self._transition_id_for_done(ticket_id)
        if not transition_id:
            transition_id = self._transition_id_for_done(ticket_id)
        if not transition_id:
            details = self.describe_transitions(ticket_id)
            hint = "; ".join(details) if details else "(none)"
            return AgentActionResult(
                success=False,
                detail=(
                    f"No closing transition found for {ticket_id}. "
                    f"Available: {hint}. "
                    f"Set JIRA_CLOSE_WORKFLOW for multi-step projects (e.g. LST). "
                    f"Run: python -m agent_network.demo.discover_jira_transitions {ticket_id}"
                ),
            )
        self._request(
            "POST",
            f"/rest/api/3/issue/{ticket_id}/transitions",
            {"transition": {"id": transition_id}},
        )
        return AgentActionResult(success=True, detail="Transitioned issue to closed/done in Jira")

    def list_tickets(
        self,
        assignee_email: Optional[str] = None,
        only_demo_tickets: bool = True,
    ) -> list[TaskReviewItem]:
        """Read-only JQL search. Never modifies issues."""
        jql_parts = [f"project = {self._allowed_project}"]
        if only_demo_tickets and self._safe_prefix:
            needle = self._safe_prefix.replace("[", "").replace("]", "").strip()
            jql_parts.append(f'summary ~ "{needle}"')
        if assignee_email:
            jql_parts.append(f'assignee = "{assignee_email}"')
        jql = " AND ".join(jql_parts) + " ORDER BY created DESC"

        body = {
            "jql": jql,
            "maxResults": 50,
            "fields": ["summary", "status", "assignee"],
        }
        try:
            data = self._request("POST", "/rest/api/3/search/jql", body)
        except RuntimeError:
            data = self._request("POST", "/rest/api/3/search", body)

        issues = data.get("issues") or data.get("values") or []
        items: list[TaskReviewItem] = []
        for issue in issues:
            fields = issue.get("fields", {})
            status = fields.get("status", {})
            category = status.get("statusCategory", {}).get("key", "")
            assignee = fields.get("assignee")
            mapped = _map_jira_status(status.get("name", ""), category)
            items.append(
                TaskReviewItem(
                    ticket_id=issue.get("key", "?"),
                    title=fields.get("summary", ""),
                    status_label=status.get("name", mapped.value),
                    status=mapped,
                    assignee_email=(assignee or {}).get("emailAddress"),
                )
            )
        logger.info("Listed %s demo ticket(s) from Jira (read-only)", len(items))
        return items

    def add_comment(self, ticket_id: str, text: str) -> AgentActionResult:
        """Add comment to a ticket (only safe-prefix demo tickets)."""
        blocked = self._assert_safe_to_modify(ticket_id)
        if blocked:
            return blocked
        payload = {"body": _adf_paragraph(text)}
        self._request("POST", f"/rest/api/3/issue/{ticket_id}/comment", payload)
        return AgentActionResult(
            success=True,
            detail=f"Comment added to {ticket_id}",
            data={"ticket_id": ticket_id},
        )
