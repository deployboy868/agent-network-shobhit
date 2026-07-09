"""
Guardrails for LLM-initiated tool calls.

Small local models (e.g. llama3.2:3b) tend to over-delegate and invent ticket IDs.
These checks run before MCP tools execute during LLM routing.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Optional

from agent_network.agent.access_policy import (
    can_view_ticket,
    deny_list_twin_queue,
    deny_view_ticket,
    deny_implement_mr,
    owner_is_direct_command,
)
from agent_network.agent.llm_text_tools import (
    LLM_OWNER_INTROSPECTION_TOOL_NAMES,
    LLM_WORK_TOOL_NAMES,
)
from agent_network.registry import DEMO_ASSIGNEE_ID, employee_by_id, employee_by_name
from agent_network.standin_policy import get_policy

if TYPE_CHECKING:
    from agent_network.agent.message_intent import MessageIntent
    from agent_network.agent.twin_chat import TwinChatSession

_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-[A-Z0-9]+)\b", re.IGNORECASE)

_DELEGATE_INTENT = re.compile(
    r"\b("
    r"delegate|hand\s*off|route\s+to|"
    r"give\s+(?:this|it)\s+to|assign\s+to\s+(?:assignee|engineer|someone)|"
    r"assign\s+(?:the\s+)?(?:demo\s+)?(?:assignee|intern|engineer)\s+a\s+ticket"
    r")\b",
    re.IGNORECASE,
)

_CREATE_TICKET = re.compile(
    r"\b(make|create|file|open|log)\b.{0,50}\b(ticket|issue)\b",
    re.IGNORECASE,
)

_THIS_TICKET = re.compile(
    r"\b(this|that|the)\s+ticket\b|status\s+of\s+(?:it|this|that)\b",
    re.IGNORECASE,
)


def ticket_ids_in_text(text: str) -> list[str]:
    return [m.upper() for m in _TICKET_RE.findall(text or "")]


def known_ticket_ids(session: "TwinChatSession") -> list[str]:
    """Ticket IDs mentioned in this conversation (most recent last)."""
    seen: list[str] = []
    for turn in session.memory_messages():
        for tid in ticket_ids_in_text(turn.get("content", "")):
            if tid not in seen:
                seen.append(tid)
    from agent_network import context_memory

    summary = context_memory.get_summary(session.conversation_id)
    if summary:
        for tid in ticket_ids_in_text(summary):
            if tid not in seen:
                seen.append(tid)
    return seen


def user_wants_create_ticket_for_self(user_message: str) -> bool:
    """User wants a ticket on their own board — not delegation to someone else."""
    text = user_message or ""
    lower = text.lower()
    if not re.search(r"\b(ticket|issue)\b", lower):
        return False
    if not re.search(r"\b(make|create|file|open|log)\b", lower):
        return False
    if re.search(r"\b(delegate|hand\s*off|route\s+to)\b", lower):
        return False
    if re.search(r"\bto\s+(assignee|engineer|demo assignee|someone else)\b", lower):
        return False
    return bool(
        re.search(
            r"\b("
            r"for me|for it|make me|create me|can you make|could you make|"
            r"can you create|could you create|assigned me|assign me|"
            r"my ticket|on my plate|put.*on my|a ticket for|"
            r"track (this|it|that)|log (this|it|that)"
            r")\b",
            lower,
        )
        or re.search(
            r"\b(create|make|open|file|log)\s+(me\s+)?a\s+(ticket|issue)\b",
            lower,
        )
    )


def user_wants_delegate(user_message: str) -> bool:
    if user_wants_create_ticket_for_self(user_message):
        return False
    lower = (user_message or "").lower()
    if bool(_DELEGATE_INTENT.search(lower)):
        return True
    return "delegate" in lower or (
        "assign" in lower and "ticket" in lower and "me" not in lower
    )


def user_refers_to_recent_ticket(user_message: str) -> bool:
    return bool(_THIS_TICKET.search(user_message or ""))


def _user_needs_ticket_data(user_message: str, intent: Optional["MessageIntent"] = None) -> bool:
    from agent_network.agent.action_reasoning import user_wants_list_tickets, user_wants_ticket_status

    if user_wants_list_tickets(user_message):
        return True
    lower = (user_message or "").lower()
    if user_wants_delegate(user_message):
        return True
    if user_wants_create_ticket_for_self(user_message):
        return True
    return bool(ticket_ids_in_text(user_message)) and user_wants_ticket_status(user_message)


def resolve_employee_id(value: str) -> str:
    """Map display names / aliases to registry employee ids."""
    if not value:
        return value
    value = value.strip()
    if employee_by_id(value):
        return value
    emp = employee_by_name(value)
    if emp:
        return emp.employee_id
    aliases = {
        "assignee": DEMO_ASSIGNEE_ID,
        "demo assignee": DEMO_ASSIGNEE_ID,
        "engineer": DEMO_ASSIGNEE_ID,
        "manager": "emp-manager",
        "demo manager": "emp-manager",
        "intern": "emp-intern",
        "demo intern": "emp-intern",
    }
    return aliases.get(value.lower(), value)


def resolve_ticket_id(
    session: "TwinChatSession",
    requested_id: str,
    user_message: str,
) -> str:
    """Prefer IDs from this chat when the user says 'this ticket'."""
    requested_id = (requested_id or "").strip().upper()
    known = known_ticket_ids(session)
    if requested_id and requested_id in known:
        return requested_id
    if user_refers_to_recent_ticket(user_message) and known:
        return known[-1]
    ids_in_user_msg = ticket_ids_in_text(user_message)
    if ids_in_user_msg:
        return ids_in_user_msg[-1]
    return requested_id


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "isError": True,
        "content": [{"type": "text", "text": json.dumps({"error": message})}],
    }


def guard_and_prepare_tool(
    session: "TwinChatSession",
    tool_name: str,
    args: dict[str, Any],
    user_message: str,
    intent: Optional["MessageIntent"] = None,
    agent_mode: bool = False,
) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """
    Validate or adjust tool args. Returns (args, blocked_result).
    If blocked_result is set, skip call_tool and return that to the LLM.
    """
    # In agent mode the LLM already chose the tool — only enforce policy/safety,
    # not keyword intent classification.
    if (
        not agent_mode
        and intent
        and intent.kind.value
        not in (
            "work_tools",
            "query_activity",
            "query_colleague_chats",
            "query_delegations",
        )
    ):
        if tool_name in LLM_WORK_TOOL_NAMES:
            return args, _tool_error(
                "Tool blocked: this message is not a work/tool request. "
                "Reply conversationally instead."
            )

    if tool_name in LLM_OWNER_INTROSPECTION_TOOL_NAMES:
        if not session.is_owner_session():
            return args, _tool_error(
                "Owner-only tool — only the twin owner can query stand-in audit/transcripts."
            )
        args = dict(args)
        args["twin_employee_id"] = session.twin_employee_id
        return args, None

    if tool_name == "jira_list_tickets" and not agent_mode and not _user_needs_ticket_data(
        user_message, intent
    ):
        return args, _tool_error(
            "Listing tickets was blocked — the user did not ask to see their backlog. "
            "Answer their actual question in plain language."
        )

    if tool_name == "twin_create_ticket_for_requester":
        if not session.requester_employee_id:
            return args, _tool_error("No requester — cannot create a personal ticket.")
        if (
            not agent_mode
            and not user_wants_create_ticket_for_self(user_message)
            and not session.is_owner_session()
        ):
            return args, _tool_error(
                "Create-ticket blocked: user did not ask for a ticket on their own board."
            )
        args = dict(args)
        args["twin_employee_id"] = session.twin_employee_id
        title = str(args.get("title", "")).strip()
        if not title:
            return args, _tool_error("Need a title for the ticket — ask what to call it.")
        from agent_network.agent.ticket_title import normalize_ticket_title

        title = normalize_ticket_title(title, user_message)
        if not title:
            return args, _tool_error(
                "Need a clear ticket title — what work should the ticket track? "
                "(e.g. Sprint Planner, not 'the same'.)"
            )
        args["title"] = title

        from agent_network.ticket_approval import (
            colleague_pending_message,
            list_pending,
            requires_ticket_approval,
        )

        colleague_session = (
            not session.is_owner_session()
            and session.requester_employee_id != session.twin_employee_id
        )
        owner_direct = owner_is_direct_command(
            session.requester_employee_id, session.twin_employee_id
        )

        # Colleague ticket ask while owner requires approval → queue + notify (never create).
        if colleague_session and requires_ticket_approval(session.twin_employee_id):
            args["requester_employee_id"] = session.requester_employee_id
            msg = colleague_pending_message(
                twin_employee_id=session.twin_employee_id,
                requester_employee_id=session.requester_employee_id,
                conversation_id=session.conversation_id,
                title=title,
                owner_name=session.employee.name,
            )
            return args, _tool_error(msg)

        # Owner cannot bypass approval queue — must use approve TA-X.
        if session.is_owner_session() and requires_ticket_approval(session.twin_employee_id):
            if list_pending(session.twin_employee_id) and not args.get("skip_approval"):
                pending = list_pending(session.twin_employee_id)
                refs = ", ".join(p["ref_code"] for p in pending)
                return args, _tool_error(
                    f"Ticket approval required. Reply approve {pending[0]['ref_code']} "
                    f"(pending: {refs}) — do not create tickets directly."
                )
            if colleague_session and not args.get("skip_approval"):
                return args, _tool_error(
                    "Owner must approve colleague ticket requests via approve TA-X."
                )

        policy = get_policy(session.twin_employee_id)
        if colleague_session and not policy.can_delegate and not owner_direct:
            return args, _tool_error(
                "Create-ticket blocked: owner forbids assigning or creating tickets "
                "while they are away."
            )

        args["requester_employee_id"] = session.requester_employee_id
        return args, None

    if tool_name == "twin_delegate_ticket":
        from agent_network.agent.access_policy import deny_delegate_from_colleague

        denied = deny_delegate_from_colleague(
            session.requester_employee_id, session.twin_employee_id
        )
        if denied:
            return args, _tool_error(denied)
        owner_command = owner_is_direct_command(
            session.requester_employee_id, session.twin_employee_id
        )
        if not owner_command and not session.is_absent():
            return args, _tool_error(
                f"{session.employee.name} is present — delegation is not available."
            )
        policy = get_policy(session.twin_employee_id)
        if not owner_command and not policy.can_delegate:
            return args, _tool_error("Stand-in policy blocks delegation.")
        if not agent_mode and not user_wants_delegate(user_message):
            return args, _tool_error(
                "Delegation blocked: the user did not explicitly ask to delegate or "
                "assign work. Ask what they need help with first; only delegate when "
                "they clearly request it."
            )
        args = dict(args)
        args["reporter_employee_id"] = session.twin_employee_id
        args["invoker_employee_id"] = session.requester_employee_id
        assignee = args.get("assignee_employee_id")
        if assignee:
            args["assignee_employee_id"] = resolve_employee_id(str(assignee))
        if not args.get("assignee_employee_id") or not employee_by_id(
            str(args["assignee_employee_id"])
        ):
            args["assignee_employee_id"] = (
                policy.default_delegate_to or DEMO_ASSIGNEE_ID
            )
        title = str(args.get("title", "")).strip()
        if not title:
            return args, _tool_error("Delegation needs a task title — ask what to delegate.")
        args["title"] = title
        return args, None

    if tool_name == "jira_get_ticket":
        args = dict(args)
        args["ticket_id"] = resolve_ticket_id(
            session, str(args.get("ticket_id", "")), user_message
        )
        if not args["ticket_id"]:
            return args, _tool_error(
                "No ticket ID provided. Use an ID from this conversation or ask the "
                "user which ticket they mean."
            )
        return args, None

    if tool_name == "jira_list_tickets":
        args = dict(args)
        twin = session.employee
        if session.requester and not session.is_owner_session():
            # Colleagues always see their own scope — never the owner's full queue.
            denied = deny_list_twin_queue(
                session.requester_employee_id,
                session.twin_employee_id,
                "twin",
            )
            requested_email = str(args.get("assignee_email", "")).strip().lower()
            twin_email = twin.email.lower()
            if requested_email and requested_email == twin_email:
                return args, _tool_error(denied or "Cannot list the owner's full backlog.")
            args["assignee_email"] = session.requester.email
        elif session.is_owner_session() and not args.get("assignee_email"):
            args["assignee_email"] = twin.email
        return args, None

    if tool_name == "gitlab_list_merge_requests":
        args = dict(args)
        state = str(args.get("state", "opened")).strip().lower() or "opened"
        if state not in ("opened", "closed", "merged", "all"):
            state = "opened"
        args["state"] = state
        try:
            limit = int(args.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        args["limit"] = max(1, min(limit, 25))
        return args, None

    if tool_name == "gitlab_link_mr_to_ticket":
        args = dict(args)
        args["ticket_id"] = resolve_ticket_id(
            session, str(args.get("ticket_id", "")), user_message
        )
        mr_url = str(args.get("mr_url", "")).strip()
        if not args["ticket_id"]:
            return args, _tool_error("ticket_id is required to link an MR.")
        if not mr_url.startswith("http"):
            return args, _tool_error("mr_url must be a full GitLab merge request URL.")
        args["mr_url"] = mr_url
        return args, None

    if tool_name == "gitlab_create_mr_from_ticket":
        denied = deny_implement_mr(
            session.requester_employee_id, session.twin_employee_id
        )
        if denied:
            return args, _tool_error(denied)
        args = dict(args)
        args["ticket_id"] = resolve_ticket_id(
            session, str(args.get("ticket_id", "")), user_message
        )
        if not args["ticket_id"]:
            return args, _tool_error(
                "ticket_id is required — use a Jira key from this conversation."
            )
        if not agent_mode:
            from agent_network.agent.action_reasoning import user_wants_implement_ticket

            if not user_wants_implement_ticket(user_message):
                return args, _tool_error(
                    "Blocked — user did not ask to implement or open an MR from a ticket."
                )
        return args, None

    return args, None


def filter_ticket_tool_result(
    session: "TwinChatSession",
    tool_name: str,
    result: dict[str, Any],
    ticket_id: str = "",
) -> dict[str, Any]:
    """Apply access policy to jira_get_ticket results for non-owners."""
    if tool_name != "jira_get_ticket" or result.get("isError"):
        return result
    try:
        data = json.loads(result["content"][0]["text"])
    except (KeyError, json.JSONDecodeError, IndexError):
        return result
    if not isinstance(data, dict) or "ticket_id" not in data:
        return result
    if not can_view_ticket(
        session.requester_employee_id, session.twin_employee_id, data
    ):
        denied = deny_view_ticket(
            session.requester_employee_id,
            session.twin_employee_id,
            data.get("ticket_id", ticket_id),
        )
        return _tool_error(denied or "You don't have access to that ticket.")
    return result


def filter_jira_list_tool_result(
    session: "TwinChatSession",
    result: dict[str, Any],
) -> dict[str, Any]:
    """Hide tickets a colleague should not see in list results."""
    if result.get("isError") or session.is_owner_session():
        return result
    try:
        items = json.loads(result["content"][0]["text"])
    except (KeyError, json.JSONDecodeError, IndexError):
        return result
    if not isinstance(items, list):
        return result

    filtered = [
        item
        for item in items
        if isinstance(item, dict)
        and can_view_ticket(session.requester_employee_id, session.twin_employee_id, item)
    ]
    return {
        "isError": False,
        "content": [{"type": "text", "text": json.dumps(filtered, indent=2)}],
    }
