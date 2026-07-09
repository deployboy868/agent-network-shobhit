"""
Decide whether a message needs a tool action or just a conversational reply.

Principle: when in doubt, talk first — only act when the user clearly asks.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from agent_network.agent.llm_tool_guards import (
    ticket_ids_in_text,
    user_refers_to_recent_ticket,
    user_wants_create_ticket_for_self,
    user_wants_delegate,
)

if TYPE_CHECKING:
    from agent_network.agent.twin_chat import TwinChatSession

_GREETING = re.compile(
    r"\b(hi|hello|hey|hiya|good morning|good afternoon|good evening|yo|sup)\b", re.I
)
_THANKS = re.compile(r"\b(thanks|thank you|thx|appreciate it|cheers)\b", re.I)
_VAGUE_HELP = re.compile(
    r"\b(i need help|need help|can you help|could you help|help me|stuck|blocked|having trouble)\b",
    re.I,
)
_EXPLAIN_ONLY = re.compile(
    r"\b(what is|what's|what are|how does|how do|why is|tell me about|explain)\b",
    re.I,
)


def user_wants_list_tickets(text: str) -> bool:
    lower = (text or "").lower()
    return any(
        p in lower
        for p in (
            "list my ticket",
            "list your ticket",
            "list ticket",
            "show my ticket",
            "show your ticket",
            "my tickets",
            "your tickets",
            "open tickets",
            "what tickets do i",
            "what tickets are",
            "which tickets",
            "any tickets",
            "tickets do i have",
            "tickets on my plate",
            "what's on my plate",
            "whats on my plate",
        )
    )


def user_wants_ticket_status(text: str) -> bool:
    """Lookup one ticket — must ask for status/lookup AND reference a ticket."""
    lower = (text or "").lower()
    has_id = bool(ticket_ids_in_text(text))
    has_pointer = user_refers_to_recent_ticket(text)
    if not has_id and not has_pointer:
        return False
    if has_id and re.search(r"\b(status|get|show|check|look\s*up|update\s+on)\b", lower):
        return True
    if has_pointer and re.search(r"\b(status|get|show)\b", lower):
        return True
    # Bare "status JIRA-123" or "JIRA-123 status"
    if has_id and ("status" in lower or lower.strip().startswith(ticket_ids_in_text(text)[0].lower())):
        return True
    return False


def user_wants_list_merge_requests(text: str) -> bool:
    lower = (text or "").lower()
    return any(
        p in lower
        for p in (
            "list merge request",
            "list mr",
            "list mrs",
            "show merge request",
            "my merge request",
            "open merge request",
        )
    ) or ("merge request" in lower and any(w in lower for w in ("list", "show", "open", "any")))


def user_wants_link_mr(text: str) -> bool:
    lower = (text or "").lower()
    return "link" in lower and ("mr" in lower or "merge" in lower or "http" in lower)


def user_wants_implement_ticket(text: str) -> bool:
    """Owner command: spawn sub-agent to open GitLab MR from a Jira ticket."""
    lower = (text or "").lower()
    if not ticket_ids_in_text(text):
        return False
    phrases = (
        "implement ",
        "generate mr",
        "generate merge request",
        "create mr",
        "create merge request",
        "open mr",
        "open merge request",
        "build mr",
        "code ",
        "start mr",
    )
    return any(p in lower for p in phrases)


def user_asked_for_tool_action(text: str) -> bool:
    """True only when the user clearly wants us to DO something or fetch live data."""
    if user_wants_create_ticket_for_self(text):
        return True
    if user_wants_delegate(text):
        return True
    if user_wants_list_tickets(text):
        return True
    if user_wants_ticket_status(text):
        return True
    if user_wants_list_merge_requests(text):
        return True
    if user_wants_link_mr(text):
        return True
    if user_wants_implement_ticket(text):
        return True
    return False


def is_talk_only_message(text: str) -> bool:
    """
    Message should get a conversational reply only — no Jira/GitLab tools.

    Even if the topic is work-related, unless they explicitly ask to act, we talk.
    """
    t = (text or "").strip()
    if not t:
        return True

    if user_asked_for_tool_action(t):
        return False

    lower = t.lower()

    if _GREETING.search(t) or _THANKS.search(t) or _VAGUE_HELP.search(t):
        return True

    # Explaining / asking about concepts — not requesting tool data
    if _EXPLAIN_ONLY.search(lower) and not user_asked_for_tool_action(t):
        return True

    # Describing assigned work without asking twin to take action
    if re.search(r"\b(assigned me|gave me|my manager|my task)\b", lower):
        if not re.search(r"\b(make|create|list|delegate|file|open|log)\b.{0,30}\b(ticket|issue)?", lower):
            return True

    # Opinions, planning, general discussion
    if re.search(r"\b(i think|maybe|probably|not sure|wondering|should i)\b", lower):
        if not user_asked_for_tool_action(t):
            return True

    return False


def requires_tool_action(session: "TwinChatSession", text: str) -> bool:
    """Final gate: should we run tools for this message?"""
    if is_talk_only_message(text):
        return False
    return user_asked_for_tool_action(text)


def detect_work_action_kind(session: "TwinChatSession", text: str) -> Optional[str]:
    """Return action kind string or None. Used by work_actions module."""
    if not requires_tool_action(session, text):
        return None
    if user_wants_create_ticket_for_self(text):
        return "create_ticket"
    if user_wants_delegate(text):
        if session.is_owner_session():
            return "delegate"
        return None
    if user_wants_link_mr(text):
        return "link_mr"
    if user_wants_implement_ticket(text):
        if session.is_owner_session():
            return "implement_mr"
        return None
    if user_wants_list_merge_requests(text):
        return "list_mrs"
    if user_wants_list_tickets(text):
        return "list_tickets"
    if user_wants_ticket_status(text):
        return "get_ticket"
    return None
