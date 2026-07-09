"""
Parse tool invocations that models narrate as JSON text (common with Ollama).

Supports multiple JSON shapes seen in the wild:
  {"name": "...", "parameters": {...}}
  {"function": "...", "arguments": {...}}
  {"tool": "...", "input": {...}}
"""

from __future__ import annotations

import json
import re
from typing import Any

# Work actions (Jira/GitLab/create) — colleague stand-in sessions.
LLM_WORK_TOOL_NAMES = frozenset(
    {
        "jira_list_tickets",
        "jira_get_ticket",
        "twin_create_ticket_for_requester",
        "gitlab_list_merge_requests",
        "gitlab_link_mr_to_ticket",
    }
)

# Owner-only — audit and colleague transcripts.
LLM_OWNER_INTROSPECTION_TOOL_NAMES = frozenset(
    {
        "twin_get_stand_in_activity",
        "twin_get_colleague_chat",
    }
)

# Owner-only — route work to other teammates.
LLM_OWNER_ACTION_TOOL_NAMES = frozenset(
    {
        "twin_delegate_ticket",
        "gitlab_create_mr_from_ticket",
    }
)

LLM_OWNER_TOOL_NAMES = LLM_OWNER_INTROSPECTION_TOOL_NAMES | LLM_OWNER_ACTION_TOOL_NAMES

# All tools the LLM may invoke (work + owner).
LLM_CHAT_TOOL_NAMES = LLM_WORK_TOOL_NAMES | LLM_OWNER_TOOL_NAMES


def iter_balanced_json_objects(text: str) -> list[str]:
    """Extract top-level {...} substrings with balanced braces."""
    objects: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        for j in range(i, n):
            ch = text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    objects.append(text[i : j + 1])
                    i = j + 1
                    break
        else:
            break
    return objects


def _normalize_invocation(obj: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    name: str | None = None
    args: Any = {}

    if isinstance(obj.get("name"), str) and obj["name"] in LLM_CHAT_TOOL_NAMES:
        name = obj["name"]
        args = obj.get("parameters") or obj.get("arguments") or obj.get("params") or {}
    elif isinstance(obj.get("function"), str) and obj["function"] in LLM_CHAT_TOOL_NAMES:
        name = obj["function"]
        args = obj.get("arguments") or obj.get("parameters") or {}
    elif isinstance(obj.get("function"), dict):
        fn = obj["function"]
        fname = fn.get("name")
        if fname in LLM_CHAT_TOOL_NAMES:
            name = fname
            args = fn.get("arguments") or fn.get("parameters") or {}
    elif isinstance(obj.get("tool"), str) and obj["tool"] in LLM_CHAT_TOOL_NAMES:
        name = obj["tool"]
        args = obj.get("input") or obj.get("parameters") or obj.get("arguments") or {}

    if not name:
        return None

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}

    if not isinstance(args, dict):
        return None

    return name, args


def parse_text_tool_invocations(content: str) -> list[tuple[str, dict[str, Any]]]:
    """Return [(tool_name, args), ...] from assistant message text."""
    if not content:
        return []

    found: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    candidates: list[str] = []

    for block in re.findall(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE):
        candidates.append(block.strip())

    candidates.extend(iter_balanced_json_objects(content))

    for raw in candidates:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        normalized = _normalize_invocation(obj)
        if not normalized:
            continue
        name, args = normalized
        key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if key in seen:
            continue
        seen.add(key)
        found.append((name, args))

    return found
