"""Execute owner/coordination intents — not Jira/GitLab work actions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from agent_network.agent.conversational import (
    conversational_fallback,
    human_help_reply,
    is_explicit_help_request,
    polish_reply,
)
from agent_network.agent.llm_router import try_llm_agent_reply, try_llm_chat_reply
from agent_network.config import is_llm_enabled
from agent_network.agent.message_intent import IntentKind, MessageIntent
from agent_network.agent.owner_intent import apply_owner_instruction
from agent_network.audit import log_twin_action
from agent_network.registry import set_employee_absent
from agent_network.standin_policy import add_absence_window, policy_summary, update_policy_from_message

if TYPE_CHECKING:
    from agent_network.agent.twin_chat import TwinChatSession

_COORDINATION = frozenset(
    {
        IntentKind.HELP,
        IntentKind.REMEMBER_INSTRUCTION,
        IntentKind.QUERY_ACTIVITY,
        IntentKind.QUERY_COLLEAGUE_CHATS,
        IntentKind.QUERY_DELEGATIONS,
        IntentKind.MANAGE_ABSENCE,
        IntentKind.SCHEDULE_ABSENCE,
        IntentKind.SHOW_POLICY,
        IntentKind.UPDATE_POLICY,
    }
)

_OWNER_INTROSPECTION = frozenset(
    {
        IntentKind.QUERY_ACTIVITY,
        IntentKind.QUERY_COLLEAGUE_CHATS,
        IntentKind.QUERY_DELEGATIONS,
    }
)


def dispatch_coordination(
    session: "TwinChatSession",
    user_message: str,
    intent: MessageIntent,
) -> Optional[str]:
    """Owner policy/absence/help only. Returns None for chat and work — caller handles those."""
    kind = intent.kind

    if kind not in _COORDINATION:
        return None

    if kind == IntentKind.HELP:
        if is_explicit_help_request(user_message):
            return human_help_reply(session, user_message)
        return None

    if kind == IntentKind.REMEMBER_INSTRUCTION and session.is_owner_session():
        return _remember_instruction(session, user_message, intent)

    if kind in _OWNER_INTROSPECTION and session.is_owner_session():
        facts = _owner_introspection_fallback(session, user_message, intent)
        if is_llm_enabled() and kind == IntentKind.QUERY_COLLEAGUE_CHATS:
            from agent_network.agent.conversational import polish_reply

            reply = polish_reply(
                session,
                user_message,
                facts,
                instruction=(
                    "Summarize ONLY from the facts provided — never invent dialogue or "
                    "claim no ticket was requested if the facts mention ticket approval."
                ),
            )
            if reply:
                return reply
        return facts

    if kind == IntentKind.MANAGE_ABSENCE and session.is_owner_session():
        return _manage_absence(session, user_message, intent)

    if kind == IntentKind.SCHEDULE_ABSENCE and session.is_owner_session():
        return _schedule_absence(session, user_message, intent)

    if kind == IntentKind.SHOW_POLICY and session.is_owner_session():
        facts = policy_summary(session.twin_employee_id)
        return polish_reply(
            session,
            user_message,
            facts,
            instruction="Explain their stand-in settings in plain English, not a config dump.",
        )

    if kind == IntentKind.UPDATE_POLICY and session.is_owner_session():
        updated = update_policy_from_message(session.twin_employee_id, user_message.lower())
        if updated:
            return polish_reply(
                session,
                user_message,
                updated,
                instruction="Confirm what changed in a natural way.",
            )
        return (
            "Sure — what do you want to change? "
            "Like turning off delegation, or whether I ping you on Teams when I route something."
        )

    return None


def _owner_introspection_fallback(
    session: "TwinChatSession",
    user_message: str,
    intent: MessageIntent,
) -> str:
    """Deterministic facts when LLM is off or unreachable."""
    kind = intent.kind
    if kind == IntentKind.QUERY_ACTIVITY:
        return session._absence_summary()
    if kind == IntentKind.QUERY_DELEGATIONS:
        return session._delegate_activity_summary()
    if kind == IntentKind.QUERY_COLLEAGUE_CHATS:
        return _reply_with_colleague_transcripts(session, user_message, intent)
    return session._absence_summary()


def dispatch_chat(session: "TwinChatSession", user_message: str) -> str:
    """Pure conversation — no tools."""
    if is_llm_enabled():
        reply = try_llm_chat_reply(session, user_message)
        return reply or conversational_fallback(session, user_message)
    return conversational_fallback(session, user_message)


def _reply_with_colleague_transcripts(
    session: "TwinChatSession",
    user_message: str,
    intent: MessageIntent,
) -> str:
    if not session.is_owner_session():
        return (
            "I can't share other people's conversations — "
            "only the twin owner can ask for that."
        )
    facts = session.fetch_colleague_conversations_for_owner(
        intent.colleague_requester_id
    )
    if intent.colleague_requester_id is None and facts.startswith("Which colleague"):
        return facts
    if is_llm_enabled():
        from agent_network.agent.conversational import polish_reply

        reply = polish_reply(
            session,
            user_message,
            facts,
            instruction=(
                "Summarize what this colleague said in natural, conversational language — "
                "like briefing your manager over Slack. Quote short phrases if helpful, "
                "but do not paste system labels or meta-instructions."
            ),
        )
        if reply:
            return reply
    return facts


# Backward-compatible alias
def dispatch_intent(
    session: "TwinChatSession",
    user_message: str,
    intent: MessageIntent,
) -> Optional[str]:
    return dispatch_coordination(session, user_message, intent)


def _remember_instruction(
    session: "TwinChatSession",
    user_message: str,
    intent: MessageIntent,
) -> str:
    text = intent.instruction_text or user_message
    lower = text.lower()
    reply = apply_owner_instruction(session.twin_employee_id, text, lower)
    if intent.disable_delegation:
        from agent_network.standin_policy import get_policy, set_policy

        policy = get_policy(session.twin_employee_id)
        policy.can_delegate = False
        set_policy(session.twin_employee_id, policy)
    log_twin_action(
        twin_employee_id=session.twin_employee_id,
        action="owner_set_instructions",
        detail=text[:200],
        data={"requester_id": session.requester_employee_id},
    )
    facts = reply
    return polish_reply(
        session,
        user_message,
        facts,
        instruction="Confirm you understood their standing instructions. Warm, brief, human.",
    )


def _manage_absence(
    session: "TwinChatSession", user_message: str, intent: MessageIntent
) -> str:
    if intent.absence_action == "absent":
        set_employee_absent(session.twin_employee_id, True)
        log_twin_action(
            twin_employee_id=session.twin_employee_id,
            action="owner_go_absent",
            detail="owner marked absent via chat",
            data={"requester_id": session.requester_employee_id},
        )
        facts = (
            "You are now marked absent. Twin will stand in for colleagues.\n"
            + policy_summary(session.twin_employee_id)
        )
        return polish_reply(
            session,
            user_message,
            facts,
            instruction="Confirm they're marked absent and you're standing in. Keep it brief.",
        )
    if intent.absence_action == "present":
        set_employee_absent(session.twin_employee_id, False)
        log_twin_action(
            twin_employee_id=session.twin_employee_id,
            action="owner_go_present",
            detail="owner marked present via chat",
            data={"requester_id": session.requester_employee_id},
        )
        return polish_reply(
            session,
            user_message,
            "Welcome back — you're marked present. Stand-in mode is off.",
            instruction="Welcome them back naturally.",
        )
    return "Want me to mark you absent or back present?"


def _schedule_absence(
    session: "TwinChatSession",
    user_message: str,
    intent: MessageIntent,
) -> str:
    import re

    dates = intent.schedule_dates or re.findall(r"(\d{4}-\d{2}-\d{2})", user_message)
    if len(dates) < 2:
        return "Give me a date range, e.g. 'I'll be away from 2026-07-01 to 2026-07-03'."
    try:
        start = datetime.fromisoformat(dates[0]).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(dates[1]).replace(tzinfo=timezone.utc)
    except ValueError:
        return "Use ISO dates like 2026-07-01."
    window = add_absence_window(session.twin_employee_id, start, end)
    log_twin_action(
        twin_employee_id=session.twin_employee_id,
        action="owner_set_absence_window",
        detail=window,
        data={"requester_id": session.requester_employee_id},
    )
    facts = (
        f"Scheduled stand-in window: {window}. "
        "Owner does not need to manually mark absent for that period."
    )
    return polish_reply(
        session,
        user_message,
        facts,
        instruction="Confirm the dates you'll cover for them.",
    )
