"""Detect and run Jira/GitLab work actions — only when clearly requested."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

from agent_network.agent.access_policy import deny_delegate_from_colleague, deny_implement_mr
from agent_network.agent.action_reasoning import detect_work_action_kind, requires_tool_action
from agent_network.agent.conversational import explain_work_result
from agent_network.agent.llm_tool_guards import user_wants_delegate

if TYPE_CHECKING:
    from agent_network.agent.twin_chat import TwinChatSession


class WorkAction(str, Enum):
    CREATE_TICKET = "create_ticket"
    DELEGATE = "delegate"
    LIST_TICKETS = "list_tickets"
    GET_TICKET = "get_ticket"
    LIST_MRS = "list_mrs"
    LINK_MR = "link_mr"
    IMPLEMENT_MR = "implement_mr"


def detect_work_action(session: "TwinChatSession", text: str) -> Optional[WorkAction]:
    kind = detect_work_action_kind(session, text)
    if not kind:
        return None
    return WorkAction(kind)


def run_work_action(session: "TwinChatSession", text: str, action: WorkAction) -> str:
    lower = text.lower()
    if action == WorkAction.CREATE_TICKET:
        return session._create_ticket_for_requester(text)
    if action == WorkAction.DELEGATE:
        return session._delegate(text, lower)
    if action == WorkAction.LIST_TICKETS:
        return session._list_tickets(lower)
    if action == WorkAction.GET_TICKET:
        tid = session._extract_ticket_id(text)
        return session._get_ticket(tid) if tid else "Which ticket ID should I look up?"
    if action == WorkAction.LIST_MRS:
        return session._list_merge_requests(lower)
    if action == WorkAction.LINK_MR:
        return session._link_mr_to_ticket(text, lower)
    if action == WorkAction.IMPLEMENT_MR:
        return session._implement_ticket_mr(text)
    return ""


def handle_work_request(session: "TwinChatSession", text: str) -> Optional[str]:
    """If (and only if) user asked for action: run tool, then explain."""
    if user_wants_delegate(text):
        denied = deny_delegate_from_colleague(
            session.requester_employee_id, session.twin_employee_id
        )
        if denied:
            return denied
    from agent_network.agent.action_reasoning import user_wants_implement_ticket

    if user_wants_implement_ticket(text):
        denied = deny_implement_mr(
            session.requester_employee_id, session.twin_employee_id
        )
        if denied:
            return denied
    if not requires_tool_action(session, text):
        return None
    action = detect_work_action(session, text)
    if not action:
        return None
    facts = run_work_action(session, text, action)
    hints = {
        WorkAction.CREATE_TICKET: "You just created a Jira ticket — include the exact ticket ID.",
        WorkAction.DELEGATE: "You delegated work — include ticket ID if one was created.",
        WorkAction.LIST_TICKETS: "Summarize their tickets clearly.",
        WorkAction.GET_TICKET: "Summarize the ticket status.",
        WorkAction.LIST_MRS: "Summarize the merge requests.",
        WorkAction.LINK_MR: "Confirm the link.",
        WorkAction.IMPLEMENT_MR: "Include the GitLab MR URL if one was opened.",
    }
    return explain_work_result(
        session,
        text,
        facts,
        action_hint=hints.get(action, ""),
    )
