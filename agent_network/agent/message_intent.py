"""
Semantic message understanding for twin chat.

When an LLM is configured, classifies each user message into an intent before
deciding whether to call Jira/GitLab tools, update stand-in policy, or just reply.
Falls back to heuristics when the LLM is off or the classifier call fails.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from agent_network.agent.conversational import is_explicit_help_request
from agent_network.agent.action_reasoning import user_asked_for_tool_action
from agent_network.agent.llm_tool_guards import user_wants_create_ticket_for_self
from agent_network.agent.owner_intent import (
    is_colleague_conversation_query,
    is_delegate_activity_query,
    is_owner_activity_query,
    is_owner_instruction_message,
    resolve_colleague_requester_from_message,
    wants_no_delegation,
)
from agent_network.config import is_llm_enabled

if TYPE_CHECKING:
    from agent_network.agent.twin_chat import TwinChatSession

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class IntentKind(str, Enum):
    CHAT = "chat"
    REMEMBER_INSTRUCTION = "remember_instruction"
    QUERY_ACTIVITY = "query_activity"
    QUERY_COLLEAGUE_CHATS = "query_colleague_chats"
    QUERY_DELEGATIONS = "query_delegations"
    MANAGE_ABSENCE = "manage_absence"
    SCHEDULE_ABSENCE = "schedule_absence"
    SHOW_POLICY = "show_policy"
    UPDATE_POLICY = "update_policy"
    WORK_TOOLS = "work_tools"
    HELP = "help"


@dataclass
class MessageIntent:
    kind: IntentKind
    instruction_text: str = ""
    disable_delegation: bool = False
    absence_action: Optional[str] = None  # "absent" | "present"
    schedule_dates: list[str] = field(default_factory=list)
    colleague_requester_id: Optional[str] = None  # owner query: which colleague's chat
    confidence: float = 1.0
    source: str = "heuristic"  # heuristic | llm


_OWNER_ONLY_INTENTS = frozenset(
    {
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


def _sanitize_owner_intent(
    session: "TwinChatSession", intent: MessageIntent
) -> MessageIntent:
    """Owner-only intents cannot run in colleague stand-in sessions."""
    if intent.kind in _OWNER_ONLY_INTENTS and not session.is_owner_session():
        return MessageIntent(IntentKind.CHAT, confidence=0.6, source=intent.source)
    return intent


_CLASSIFY_PROMPT = """You classify messages to a digital twin assistant. Return ONLY valid JSON.

Intents:
- chat — greetings, thanks, small talk, clarifying questions, acknowledgments. NO tools needed.
- remember_instruction — owner tells the twin how to behave while away (rules, preferences, "keep in mind", "don't delegate", etc.)
- query_activity — owner asks what happened / what the twin did while they were away (actions, audit-style summary)
- query_colleague_chats — owner asks what a colleague said, who messaged, or wants stand-in conversation transcripts ("what did the intern tell you?", "who reached out?")
- query_delegations — owner asks specifically whether tickets were assigned/delegated to others
- manage_absence — owner wants to go absent now or come back present ("I'm OOO", "I'm back")
- schedule_absence — owner gives date range for planned absence ("away July 1-3")
- show_policy — owner wants to see current stand-in settings/rules
- update_policy — owner toggles delegation/notify flags ("turn off notifications", "allow delegate")
- work_tools — user wants an ACTION or live data: create ticket, list tickets, ticket status, merge requests, delegate to someone else. "make me a ticket" is work_tools NOT chat.
- help — ONLY when user explicitly wants a command menu ("help", "commands", "what can you do"). "I need help", "hi", "can you help me" are chat, NOT help.

Rules:
- If the owner is giving rules for future absence, use remember_instruction — NOT work_tools.
- If asking about past twin actions, use query_activity or query_delegations — NOT work_tools.
- If owner wants what someone said in chat (intern, assignee, colleague), use query_colleague_chats — NOT work_tools.
- work_tools only when they explicitly ask to create, list, look up, link, or delegate — not when merely describing work or asking for advice.
- "make me a ticket", "list my tickets", "delegate X" → work_tools.
- "my manager assigned me X" (no action verb) → chat. "what is X" → chat.
- When unsure between chat and work_tools, prefer chat unless they clearly asked you to do something.
- Owner-only intents (query_colleague_chats, query_activity, query_delegations, remember_instruction, manage_absence, schedule_absence, show_policy, update_policy) apply ONLY when "Owner session: true" in context. If Owner session is false, use chat — colleagues cannot query other people's conversations.
- For query_colleague_chats, set colleague_requester to the specific person mentioned (intern, assignee, Demo Intern, etc.). Use null only if no specific person is named.

JSON shape:
{
  "intent": "<one of the intent names above>",
  "instruction_text": "<full instruction to save, if remember_instruction, else empty>",
  "disable_delegation": <true if owner forbids assigning/delegating tickets>,
  "absence_action": "<absent|present|null>",
  "schedule_dates": ["YYYY-MM-DD", ...],
  "colleague_requester": "<who the owner is asking about: intern, assignee, observer, a demo name, or null if unclear>",
  "confidence": <0.0-1.0>
}"""


def classify_message(session: "TwinChatSession", user_message: str) -> MessageIntent:
    if is_llm_enabled():
        try:
            intent = _sanitize_owner_intent(
                session, _llm_classify(session, user_message)
            )
            if intent.confidence >= 0.5:
                return intent
        except Exception as e:
            logger.warning("LLM intent classification failed: %s", e)
    return _sanitize_owner_intent(
        session, _heuristic_classify(session, user_message)
    )


def _heuristic_classify(session: "TwinChatSession", user_message: str) -> MessageIntent:
    lower = user_message.lower().strip()
    if lower in {"help", "?", "commands"}:
        return MessageIntent(IntentKind.HELP)

    if session.is_owner_session():
        if any(p in lower for p in ("go absent", "mark absent", "i'm ooo", "im ooo", "going absent")):
            return MessageIntent(IntentKind.MANAGE_ABSENCE, absence_action="absent")
        if any(p in lower for p in ("go present", "mark present", "i'm back", "im back")):
            return MessageIntent(IntentKind.MANAGE_ABSENCE, absence_action="present")
        if any(
            p in lower
            for p in ("stand-in settings", "stand-in policy", "stand in settings", "show stand-in")
        ):
            return MessageIntent(IntentKind.SHOW_POLICY)
        if "stand-in rules" in lower or "stand in rules" in lower:
            return MessageIntent(IntentKind.UPDATE_POLICY)
        if "absent from" in lower:
            dates = _DATE_RE.findall(user_message)
            return MessageIntent(IntentKind.SCHEDULE_ABSENCE, schedule_dates=dates)
        if is_owner_instruction_message(lower) and not is_owner_activity_query(lower):
            return MessageIntent(
                IntentKind.REMEMBER_INSTRUCTION,
                instruction_text=user_message.strip(),
                disable_delegation=wants_no_delegation(lower),
            )
        if is_delegate_activity_query(lower):
            return MessageIntent(IntentKind.QUERY_DELEGATIONS)
        if is_colleague_conversation_query(lower):
            colleague_id = resolve_colleague_requester_from_message(
                user_message, session.twin_employee_id
            )
            return MessageIntent(
                IntentKind.QUERY_COLLEAGUE_CHATS,
                colleague_requester_id=colleague_id,
            )
        if is_owner_activity_query(lower):
            return MessageIntent(IntentKind.QUERY_ACTIVITY)

    if user_asked_for_tool_action(user_message):
        return MessageIntent(IntentKind.WORK_TOOLS)

    return MessageIntent(IntentKind.CHAT, confidence=0.6)


def _looks_like_work_request(lower: str) -> bool:
    """Deprecated — use action_reasoning.user_asked_for_tool_action."""
    return user_asked_for_tool_action(lower)


def _llm_classify(session: "TwinChatSession", user_message: str) -> MessageIntent:
    from agent_network.agent.llm_router import _make_client, _model_name

    client = _make_client()
    model = _model_name()

    owner = session.is_owner_session()
    context = (
        f"Twin owner: {session.employee.name}. "
        f"Requester: {session.requester.name if session.requester else 'unknown'}. "
        f"Owner session: {owner}. "
        f"Owner currently {'absent' if session.is_absent() else 'present'}."
    )
    recent = session.memory_messages()[-4:]
    history = ""
    if recent:
        lines = [f"{t.get('role', '?')}: {t.get('content', '')[:200]}" for t in recent]
        history = "Recent conversation:\n" + "\n".join(lines)

    messages = [
        {"role": "system", "content": _CLASSIFY_PROMPT},
        {"role": "user", "content": f"{context}\n{history}\n\nClassify this message:\n{user_message}"},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        tool_choice="none",
    )
    raw = (response.choices[0].message.content or "").strip()
    data = _parse_json_object(raw)
    return _intent_from_json(data, user_message, session)


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def _resolve_colleague_for_intent(
    session: "TwinChatSession",
    user_message: str,
    data: dict[str, Any],
) -> Optional[str]:
    twin_id = session.twin_employee_id
    colleague_id = resolve_colleague_requester_from_message(user_message, twin_id)
    if colleague_id:
        return colleague_id
    colleague_raw = data.get("colleague_requester") or data.get("colleague")
    if colleague_raw and str(colleague_raw).strip().lower() not in ("null", "none", ""):
        return resolve_colleague_requester_from_message(str(colleague_raw), twin_id)
    return None


def _intent_from_json(
    data: dict[str, Any],
    user_message: str,
    session: "TwinChatSession",
) -> MessageIntent:
    name = str(data.get("intent", "chat")).strip().lower()
    try:
        kind = IntentKind(name)
    except ValueError:
        kind = IntentKind.CHAT

    if kind == IntentKind.HELP and not is_explicit_help_request(user_message):
        kind = IntentKind.CHAT

    if kind == IntentKind.WORK_TOOLS and not user_asked_for_tool_action(user_message):
        kind = IntentKind.CHAT

    instruction = str(data.get("instruction_text", "") or "").strip()
    if kind == IntentKind.REMEMBER_INSTRUCTION and not instruction:
        instruction = user_message.strip()

    dates = data.get("schedule_dates") or []
    if not isinstance(dates, list):
        dates = _DATE_RE.findall(user_message)

    absence = data.get("absence_action")
    if absence not in ("absent", "present"):
        absence = None

    try:
        confidence = float(data.get("confidence", 0.8))
    except (TypeError, ValueError):
        confidence = 0.8

    disable = bool(data.get("disable_delegation", False))
    if kind == IntentKind.REMEMBER_INSTRUCTION and not disable:
        disable = wants_no_delegation(user_message.lower())

    colleague_id = None
    if kind == IntentKind.QUERY_COLLEAGUE_CHATS:
        colleague_id = _resolve_colleague_for_intent(session, user_message, data)

    return MessageIntent(
        kind=kind,
        instruction_text=instruction,
        disable_delegation=disable,
        absence_action=absence,
        schedule_dates=[str(d) for d in dates],
        colleague_requester_id=colleague_id,
        confidence=confidence,
        source="llm",
    )


def execute_intent(
    session: "TwinChatSession",
    user_message: str,
    intent: MessageIntent,
) -> Optional[str]:
    """Run the classified intent. Returns None to fall through to keyword router."""
    from agent_network.agent.intent_handlers import dispatch_intent

    return dispatch_intent(session, user_message, intent)
