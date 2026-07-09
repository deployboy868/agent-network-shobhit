"""
Optional LLM routing for twin chat (Ollama local or OpenAI tool-calling).

Falls back to keyword router when no LLM is configured or the call fails.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, TYPE_CHECKING

from agent_network.config import (
    grok_base_url,
    grok_model,
    groq_base_url,
    groq_model,
    is_llm_enabled,
    llm_provider,
    ollama_base_url,
    ollama_model,
    openai_model,
)
from agent_network.agent.llm_text_tools import (
    LLM_CHAT_TOOL_NAMES,
    LLM_OWNER_TOOL_NAMES,
    LLM_WORK_TOOL_NAMES,
)
from agent_network.agent.llm_tool_exec import (
    collect_invocations,
    run_tool_batch,
    summarize_tool_results,
)
from agent_network.agent.llm_tool_guards import known_ticket_ids

if TYPE_CHECKING:
    from agent_network.agent.message_intent import MessageIntent
    from agent_network.agent.twin_chat import TwinChatSession

logger = logging.getLogger(__name__)

_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "jira_list_tickets",
            "description": (
                "List Jira tickets for an assignee. ONLY when the user explicitly "
                "asks to see tickets/backlog/work items. Never for policy questions "
                "or 'what happened while I was away'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "assignee_email": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jira_get_ticket",
            "description": (
                "Get one Jira ticket by ID. Use ONLY ticket IDs already mentioned "
                "in this conversation — never invent IDs."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ticket_id": {"type": "string"}},
                "required": ["ticket_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "twin_create_ticket_for_requester",
            "description": (
                "Create a Jira ticket assigned to the person asking. Use when they want "
                "work tracked on THEIR plate (e.g. 'make me a ticket for Sprint Planner'). "
                "Do NOT use for routing work to someone else — that is owner-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "twin_employee_id": {
                        "type": "string",
                        "description": "Registry id of the twin owner (e.g. emp-manager).",
                    },
                    "requester_employee_id": {
                        "type": "string",
                        "description": "Registry id of the person asking (assignee).",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": [
                    "twin_employee_id",
                    "requester_employee_id",
                    "title",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gitlab_list_merge_requests",
            "description": "List GitLab merge requests in the configured project (read-only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "opened, closed, merged, or all"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gitlab_link_mr_to_ticket",
            "description": (
                "Link a GitLab MR URL to a Jira ticket (Jira comment only). "
                "Use ticket IDs from this conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string"},
                    "mr_url": {"type": "string"},
                },
                "required": ["ticket_id", "mr_url"],
            },
        },
    },
]

_OWNER_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "twin_get_stand_in_activity",
            "description": (
                "Read the stand-in audit log: tickets created for colleagues, tickets "
                "delegated, and other actions while the owner was away. Call when you "
                "need factual grounding about stand-in activity — not for casual chat."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "twin_employee_id": {
                        "type": "string",
                        "description": "Twin owner registry id (e.g. emp-manager).",
                    },
                },
                "required": ["twin_employee_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "twin_get_colleague_chat",
            "description": (
                "Fetch stand-in chat transcript with one colleague. Use when the owner "
                "asks what someone said and you need the actual messages. Pass "
                "colleague_name or colleague_employee_id. Do not invent dialogue."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "twin_employee_id": {"type": "string"},
                    "colleague_employee_id": {
                        "type": "string",
                        "description": "e.g. emp-intern",
                    },
                    "colleague_name": {
                        "type": "string",
                        "description": "e.g. intern, Demo Assignee",
                    },
                },
                "required": ["twin_employee_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "twin_delegate_ticket",
            "description": (
                "Owner-only: create a ticket and assign it to ANOTHER teammate. "
                "Use ONLY when the twin owner explicitly wants work routed/delegated "
                "while they are absent — never for colleagues asking on their own behalf."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reporter_employee_id": {
                        "type": "string",
                        "description": "Registry id of the twin owner (e.g. emp-manager).",
                    },
                    "assignee_employee_id": {
                        "type": "string",
                        "description": "Registry id to delegate to (e.g. emp-assignee).",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": [
                    "reporter_employee_id",
                    "assignee_employee_id",
                    "title",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gitlab_create_mr_from_ticket",
            "description": (
                "Owner-only sub-agent: read a Jira ticket, generate a small file via Groq, "
                "open a GitLab merge request, and link it back to the ticket. Use when the "
                "owner asks to implement, generate MR, or code a specific ticket ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "Jira key e.g. LST-12345 from this conversation.",
                    },
                },
                "required": ["ticket_id"],
            },
        },
    },
]

assert LLM_WORK_TOOL_NAMES == {t["function"]["name"] for t in _TOOL_DEFS}
assert LLM_OWNER_TOOL_NAMES == {t["function"]["name"] for t in _OWNER_TOOL_DEFS}


def llm_backend_label() -> str:
    provider = llm_provider()
    if provider == "groq":
        return f"Groq ({groq_model()})"
    if provider == "grok":
        return f"Grok ({grok_model()})"
    if provider == "ollama":
        return f"Ollama ({ollama_model()})"
    if provider == "openai":
        return f"OpenAI ({openai_model()})"
    return "keyword router"


def _make_client():
    from openai import OpenAI
    import os

    provider = llm_provider()
    if provider == "ollama":
        base = ollama_base_url()
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return OpenAI(base_url=base, api_key="ollama", timeout=90.0)
    if provider == "groq":
        return OpenAI(
            base_url=groq_base_url(),
            api_key=os.environ["GROQ_API_KEY"],
            timeout=90.0,
        )
    if provider == "grok":
        return OpenAI(
            base_url=grok_base_url(),
            api_key=os.environ["GROK_API_KEY"],
            timeout=90.0,
        )
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=90.0)


def _model_name() -> str:
    provider = llm_provider()
    if provider == "groq":
        return groq_model()
    if provider == "grok":
        return grok_model()
    if provider == "ollama":
        return ollama_model()
    return openai_model()


from agent_network.agent.conversational import HUMAN_VOICE, conversational_system_prompt


def try_llm_chat_reply(
    session: "TwinChatSession",
    user_message: str,
    intent: Optional["MessageIntent"] = None,
    context_facts: Optional[str] = None,
) -> Optional[str]:
    """Conversational reply without tools — for chat, confirmations, and summaries."""
    if not is_llm_enabled():
        return None
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        return None

    client = _make_client()
    model = _model_name()
    system = conversational_system_prompt(session)
    system += (
        "\n\nReply to the user's latest message only. No tools. "
        "If context facts are provided below, weave them in naturally."
    )
    if context_facts:
        system += f"\n\nFacts from the system (use these, do not invent):\n{context_facts}"

    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for turn in session.memory_messages():
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            tool_choice="none",
        )
        content = (response.choices[0].message.content or "").strip()
        return content or None
    except Exception as e:
        logger.warning("LLM chat reply failed (%s): %s", llm_provider(), e)
        return None


def twin_employee_id_hint(session: "TwinChatSession") -> str:
    return f"Twin owner employee_id for tools: {session.twin_employee_id}"


def agent_reasoning_prompt(session: "TwinChatSession") -> str:
    """How the LLM should think before acting — policy + tool choice."""
    from agent_network.standin_policy import get_policy

    policy = get_policy(session.twin_employee_id)
    owner = session.is_owner_session()
    lines = [
        "\n\nReasoning discipline (internal — do not recite this checklist to the user):",
        "1. What are they actually asking — casual chat, a factual recap, or an action?",
        "2. Do you already have enough context in this thread? If yes, reply naturally without tools.",
    ]
    if owner:
        lines.extend(
            [
                "3. Stand-in history / tickets created while away → twin_get_stand_in_activity.",
                "4. What a specific colleague said → twin_get_colleague_chat (name or employee id).",
                "   Summarize transcripts naturally — never paste internal tool headers.",
                "5. Jira/GitLab/list/delegate/create only when they clearly need live data or action.",
                "6. The owner has full authority: their direct assign/delegate commands override "
                "stand-in rules meant for colleagues.",
                "7. Before acting on behalf of colleagues (not the owner), check policy:",
            ]
        )
        step_err, step_inv = "8", "9"
    else:
        lines.extend(
            [
                "3. You cannot read audit logs or other people's transcripts — only the owner can.",
                "4. You cannot delegate work to other teammates — only the owner can route tasks.",
                "5. Jira/GitLab/list/create only when they clearly need live data or action.",
                "6. Before creating tickets for the requester, check policy:",
            ]
        )
        step_err, step_inv = "7", "8"
    lines.extend(
        [
            f"   - can_delegate={'yes' if policy.can_delegate else 'NO for colleagues while away — owner can always direct you'}",
            f"   - owner is {'absent' if session.is_absent() else 'present'} "
            f"(colleague delegation only when absent; owner direct commands always win).",
            f"{step_err}. If a tool returns an error/blocked message, tell the user plainly.",
            f"{step_inv}. Never invent ticket IDs or chat lines — only cite tool results.",
            f"\n{twin_employee_id_hint(session)}",
            f"\n{HUMAN_VOICE}",
        ]
    )
    return "\n".join(lines)


def _run_agent_tool_loop(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    tool_defs: list[dict[str, Any]],
    allowed_tools: frozenset[str],
    session: "TwinChatSession",
    user_message: str,
    intent: Optional["MessageIntent"] = None,
    max_rounds: int = 2,
) -> Optional[str]:
    """Multi-round tool loop: LLM decides, guards enforce policy at execution."""
    for round_idx in range(max_rounds):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tool_defs,
                tool_choice="auto",
                temperature=0 if round_idx == 0 else 0.25,
            )
        except Exception as e:
            logger.warning("LLM agent round %s failed (%s): %s", round_idx, llm_provider(), e)
            return None

        choice = response.choices[0].message
        invocations = collect_invocations(choice, allowed_tools=allowed_tools)

        if not invocations:
            content = (choice.content or "").strip()
            if content and not _looks_like_unparsed_tool_json(content):
                return content
            if round_idx == 0 and content:
                retry = collect_invocations(
                    type("Msg", (), {"content": content, "tool_calls": []})(),
                    allowed_tools=allowed_tools,
                )
                if retry:
                    invocations = retry
                else:
                    return content or None
            return content or None

        tool_messages, executed = run_tool_batch(
            session,
            user_message,
            invocations,
            intent=intent,
            agent_mode=True,
            allowed_tools=allowed_tools,
        )
        tool_call_payload = [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
            for call_id, name, args in executed
        ]
        messages.append(
            {
                "role": "assistant",
                "content": choice.content or "",
                "tool_calls": tool_call_payload,
            }
        )
        messages.extend(tool_messages)

        if round_idx == max_rounds - 1:
            try:
                final = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.25,
                )
                reply = (final.choices[0].message.content or "").strip()
                if reply:
                    return reply
            except Exception as e:
                logger.warning("LLM agent final synthesis failed: %s", e)
            return summarize_tool_results(tool_messages)

    return None


def try_llm_agent_reply(
    session: "TwinChatSession",
    user_message: str,
    intent: Optional["MessageIntent"] = None,
) -> Optional[str]:
    """
    Primary LLM path: model reasons about whether to check logs, fetch transcripts,
    call Jira/GitLab, or reply conversationally. Guards enforce owner policy at execution.
    """
    if not is_llm_enabled():
        return None
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        return None

    client = _make_client()
    model = _model_name()

    owner = session.is_owner_session()
    tool_defs: list[dict[str, Any]] = list(_TOOL_DEFS)
    allowed = LLM_WORK_TOOL_NAMES
    if owner:
        tool_defs.extend(_OWNER_TOOL_DEFS)
        allowed = LLM_CHAT_TOOL_NAMES

    system = session.llm_system_prompt() + agent_reasoning_prompt(session)
    known = known_ticket_ids(session)
    if known:
        system += (
            f"\nTicket IDs mentioned in this conversation (use these, do not invent others): "
            f"{', '.join(known)}."
        )

    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for turn in session.memory_messages():
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    return _run_agent_tool_loop(
        client,
        model,
        messages,
        tool_defs,
        allowed,
        session,
        user_message,
        intent=intent,
    )


def try_llm_owner_reply(
    session: "TwinChatSession",
    user_message: str,
    intent: Optional["MessageIntent"] = None,
) -> Optional[str]:
    """Owner introspection — delegates to unified agent loop."""
    if not session.is_owner_session():
        return None
    return try_llm_agent_reply(session, user_message, intent=intent)


def try_llm_reply(
    session: "TwinChatSession",
    user_message: str,
    intent: Optional["MessageIntent"] = None,
) -> Optional[str]:
    """Backward-compatible alias — unified agent loop."""
    return try_llm_agent_reply(session, user_message, intent=intent)


def _looks_like_unparsed_tool_json(text: str) -> bool:
    from agent_network.agent.llm_text_tools import parse_text_tool_invocations

    return bool(parse_text_tool_invocations(text))
