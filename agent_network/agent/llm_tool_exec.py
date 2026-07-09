"""
Execute LLM tool invocations (structured API or parsed text) with guards and filters.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from agent_network.agent.llm_text_tools import (
    LLM_CHAT_TOOL_NAMES,
    LLM_OWNER_TOOL_NAMES,
    LLM_WORK_TOOL_NAMES,
    parse_text_tool_invocations,
)
from agent_network.agent.llm_tool_guards import (
    filter_jira_list_tool_result,
    filter_ticket_tool_result,
    guard_and_prepare_tool,
)
from agent_network.mcp_server.tools_registry import call_tool

if TYPE_CHECKING:
    from agent_network.agent.twin_chat import TwinChatSession

logger = logging.getLogger(__name__)


def collect_invocations(
    choice: Any,
    allowed_tools: frozenset[str] | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    """
    Normalize tool calls from an OpenAI-style assistant message.
    Returns [(call_id, tool_name, args), ...].
    """
    allowed = allowed_tools or LLM_CHAT_TOOL_NAMES
    invocations: list[tuple[str, str, dict[str, Any]]] = []

    tool_calls = getattr(choice, "tool_calls", None) or []
    for call in tool_calls:
        name = getattr(getattr(call, "function", None), "name", None)
        if name not in allowed:
            logger.warning("LLM requested unknown tool: %s", name)
            continue
        raw_args = getattr(getattr(call, "function", None), "arguments", None) or "{}"
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            logger.warning("Invalid tool arguments JSON for %s: %s", name, raw_args)
            args = {}
        if not isinstance(args, dict):
            args = {}
        invocations.append((call.id, name, args))

    if not invocations:
        content = getattr(choice, "content", None) or ""
        for i, (name, args) in enumerate(parse_text_tool_invocations(content)):
            invocations.append((f"parsed_{i}", name, args))

    return invocations


def run_tool_batch(
    session: "TwinChatSession",
    user_message: str,
    invocations: list[tuple[str, str, dict[str, Any]]],
    intent: Optional[Any] = None,
    agent_mode: bool = False,
    allowed_tools: frozenset[str] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[str, str, dict[str, Any]]]]:
    """
    Execute tools with guards. Returns (tool_result_messages, executed_invocations).
    """
    allowed = allowed_tools or LLM_CHAT_TOOL_NAMES
    tool_messages: list[dict[str, Any]] = []
    executed: list[tuple[str, str, dict[str, Any]]] = []

    for call_id, name, raw_args in invocations:
        if name not in allowed:
            result = {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"error": f"Unknown tool: {name}"}),
                    }
                ],
            }
            executed.append((call_id, name, raw_args))
        else:
            args, blocked = guard_and_prepare_tool(
                session,
                name,
                raw_args,
                user_message,
                intent=intent,
                agent_mode=agent_mode,
            )
            if blocked:
                result = blocked
            else:
                result = call_tool(name, args)
                if name == "jira_get_ticket":
                    result = filter_ticket_tool_result(
                        session,
                        name,
                        result,
                        ticket_id=str(args.get("ticket_id", "")),
                    )
                elif name == "jira_list_tickets":
                    result = filter_jira_list_tool_result(session, result)
            executed.append((call_id, name, args))

        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": result["content"][0]["text"],
            }
        )

    return tool_messages, executed


def summarize_tool_results(tool_messages: list[dict[str, Any]]) -> Optional[str]:
    """Plain-language summary when the follow-up LLM call fails or returns empty."""
    parts: list[str] = []
    for msg in tool_messages:
        raw = msg.get("content", "")
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("error"):
                parts.append(f"Couldn't do that — {data['error']}")
                continue
            if isinstance(data, dict) and data.get("success") is False:
                parts.append(data.get("detail", "That didn't work — want to try differently?"))
                continue
            if isinstance(data, dict) and data.get("summary"):
                parts.append(str(data["summary"])[:2000])
                continue
            if isinstance(data, dict) and data.get("transcript"):
                # Raw transcript is context for the LLM — do not dump verbatim to the user.
                colleague = data.get("colleague", "colleague")
                parts.append(
                    f"Pulled the stand-in chat with {colleague}. "
                    "Summarize it naturally for the owner."
                )
                continue
            if isinstance(data, dict) and data.get("ticket_id"):
                assignee = data.get("assignee_name") or data.get("assignee_employee_id", "")
                who = f" for {assignee}" if assignee else ""
                line = f"Done — created {data['ticket_id']}{who}."
                if data.get("title"):
                    line += f" ({data['title'][:50]})"
                if data.get("owner_notification"):
                    line += f" {data['owner_notification']}"
                parts.append(line)
                continue
            if isinstance(data, dict) and data.get("success") and data.get("detail"):
                tid = data.get("ticket_id")
                if tid:
                    parts.append(f"Done — {data['detail']}")
                    continue
            if isinstance(data, list):
                if not data:
                    parts.append("Nothing turned up for that.")
                elif isinstance(data[0], dict) and "ticket_id" in data[0]:
                    if len(data) == 1:
                        t = data[0]
                        parts.append(
                            f"You've got one ticket: {t['ticket_id']} ({t.get('status', '?')}) — "
                            f"{str(t.get('title', ''))[:60]}"
                        )
                    else:
                        lines = [
                            f"• {i['ticket_id']} — {str(i.get('title', ''))[:50]}"
                            for i in data[:8]
                        ]
                        parts.append(
                            f"Here are {len(data)} tickets on your plate:\n" + "\n".join(lines)
                        )
                elif isinstance(data[0], dict) and "iid" in data[0]:
                    lines = [
                        f"• !{mr.get('iid')} ({mr.get('state')}) — {str(mr.get('title', ''))[:45]}"
                        for mr in data[:8]
                    ]
                    parts.append(f"Found {len(data)} open MRs:\n" + "\n".join(lines))
                else:
                    parts.append(raw[:500])
                continue
        except json.JSONDecodeError:
            pass
        if raw and not raw.startswith("{"):
            parts.append(raw[:500])
    return "\n".join(parts) if parts else None
