"""
Classify owner messages into durable rule operations (add / update / revoke).

Uses the LLM to reason about standing rules vs queries/commands when available;
falls back to heuristics for offline tests.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from agent_network.agent.owner_intent import (
    extract_instruction_text,
    is_owner_instruction_message,
    wants_no_delegation,
)
from agent_network.config import is_llm_enabled

logger = logging.getLogger(__name__)

_SKIP_CUES = (
    "what happened",
    "what did you do",
    "what did the intern",
    "what did the assignee",
    "who messaged",
    "who said",
    "show stand-in",
    "stand-in settings",
    "stand in settings",
)

_REVOKE_CUES = (
    "forget that",
    "forget the",
    "forget about",
    "forget the rule",
    "remove that rule",
    "remove the rule",
    "delete that rule",
    "cancel that rule",
    "ignore that rule",
    "ignore that instruction",
    "don't follow that",
    "do not follow that",
    "stop following",
    "never mind that",
    "scratch that",
    "revoke",
    "undo that rule",
)

_UPDATE_CUES = (
    "instead tell them",
    "instead say",
    "change that to",
    "update that to",
    "update the rule",
    "actually tell them",
    "rather tell them",
    "rather say",
    "replace that with",
)

_OPERATIONAL_CUES = (
    "go absent",
    "mark absent",
    "go present",
    "mark present",
    "i'm back",
    "im back",
    "approve ta-",
    "reject ta-",
    "pending approval",
)


@dataclass
class OwnerRuleClassification:
    """Result of classifying an owner message."""

    operations: list[dict[str, Any]] = field(default_factory=list)
    message_kind: str = "unknown"
    reasoning: str = ""
    policy_effects: dict[str, Optional[bool]] = field(default_factory=dict)

    @property
    def is_rule_mutation(self) -> bool:
        return any(
            op.get("action") in ("add", "update", "revoke") for op in self.operations
        )


def classify_owner_message(
    twin_employee_id: str,
    user_message: str,
    assistant_reply: str = "",
) -> OwnerRuleClassification:
    """Classify owner text with LLM reasoning when available."""
    text = (user_message or "").strip()
    if not text:
        return OwnerRuleClassification(
            operations=[{"action": "none"}],
            message_kind="empty",
            reasoning="Empty message.",
        )

    if is_llm_enabled():
        llm_result = _llm_classify(twin_employee_id, text, assistant_reply)
        if llm_result is not None:
            return llm_result

    if not should_extract_rules(text):
        return OwnerRuleClassification(
            operations=[{"action": "none"}],
            message_kind="information_query",
            reasoning="Heuristic: read-only or operational message.",
        )

    ops = _heuristic_classify(text, _load_active_rules(twin_employee_id))
    policy = _heuristic_policy_effects(text, ops)
    return OwnerRuleClassification(
        operations=ops,
        message_kind="standing_rule" if any(o.get("action") != "none" for o in ops) else "casual_chat",
        reasoning="Heuristic classification (LLM unavailable).",
        policy_effects=policy,
    )


def classify_owner_rule_ops(
    twin_employee_id: str,
    user_message: str,
    assistant_reply: str = "",
) -> list[dict[str, Any]]:
    """Backward-compatible: return operations list only."""
    return classify_owner_message(
        twin_employee_id, user_message, assistant_reply
    ).operations


def derive_policy_from_rules(twin_employee_id: str) -> dict[str, bool]:
    """
    Read all active owner rules and derive stand-in policy flags.
    Uses LLM reasoning when available; heuristics otherwise.
    """
    from agent_network.standin_policy import get_policy, set_policy

    rules = _load_active_rules(twin_employee_id)
    policy = get_policy(twin_employee_id)

    if is_llm_enabled() and rules:
        llm_flags = _llm_derive_policy(rules)
        if llm_flags is not None:
            if llm_flags.get("require_ticket_approval") is not None:
                policy.require_ticket_approval = bool(
                    llm_flags["require_ticket_approval"]
                )
            if llm_flags.get("can_delegate") is not None:
                policy.can_delegate = bool(llm_flags["can_delegate"])
            set_policy(twin_employee_id, policy)
            return {
                "require_ticket_approval": policy.require_ticket_approval,
                "can_delegate": policy.can_delegate,
            }

    require_approval = policy.require_ticket_approval
    can_delegate = policy.can_delegate

    for rule in rules:
        tags = rule.get("policy_tags") or {}
        if tags.get("require_ticket_approval"):
            require_approval = True
        if tags.get("can_delegate") is False:
            can_delegate = False
        text = rule.get("rule_text", "")
        from agent_network.ticket_approval import (
            rule_requires_ticket_approval,
            wants_ticket_hold_and_notify,
        )

        if rule_requires_ticket_approval(text) or wants_ticket_hold_and_notify(text):
            require_approval = True
        if wants_no_delegation(text.lower()):
            can_delegate = False

    policy.require_ticket_approval = require_approval
    policy.can_delegate = can_delegate
    set_policy(twin_employee_id, policy)
    return {
        "require_ticket_approval": require_approval,
        "can_delegate": can_delegate,
    }


def _load_active_rules(twin_employee_id: str) -> list[dict]:
    from agent_network import owner_instruction_memory

    return owner_instruction_memory.list_active_rules(twin_employee_id)


def should_extract_rules(user_message: str) -> bool:
    """False for read-only owner queries that should not become rules (offline fallback)."""
    from agent_network.agent.conversational import is_explicit_help_request
    from agent_network.agent.owner_intent import (
        is_delegate_activity_query,
        is_owner_activity_query,
    )

    text = (user_message or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower in {"help", "?", "commands"}:
        return False
    if is_explicit_help_request(text):
        return False
    if is_owner_activity_query(lower) or is_delegate_activity_query(lower):
        return False
    if any(cue in lower for cue in _SKIP_CUES):
        return False
    if any(cue in lower for cue in _OPERATIONAL_CUES):
        return False
    if re.search(r"\bapprove\s+ta-\d+", lower) or re.search(r"\breject\s+ta-\d+", lower):
        return False
    return True


def _llm_classify(
    twin_employee_id: str,
    user_message: str,
    assistant_reply: str,
) -> OwnerRuleClassification | None:
    try:
        from agent_network.agent.llm_router import _make_client, _model_name

        active = _load_active_rules(twin_employee_id)
        rules_block = "No active rules yet."
        if active:
            lines = []
            for r in active:
                tags = r.get("policy_tags") or {}
                tag_bit = f" tags={json.dumps(tags)}" if tags else ""
                lines.append(f"  [{r['id']}] {r['rule_text']}{tag_bit}")
            rules_block = "Active owner rules:\n" + "\n".join(lines)

        schema = (
            "Return ONLY valid JSON (no markdown fences):\n"
            "{\n"
            '  "message_kind": "standing_rule_add|standing_rule_update|standing_rule_revoke|'
            'information_query|operational_command|casual_chat",\n'
            '  "reasoning": "one sentence: why this is or is not a standing rule",\n'
            '  "operations": [\n'
            '    {"action": "add", "rule_text": "normalized standing instruction", '
            '"policy_tags": {"require_ticket_approval": true, "can_delegate": false}},\n'
            '    {"action": "update", "rule_id": 2, "rule_text": "...", "policy_tags": {}},\n'
            '    {"action": "revoke", "rule_id": 3},\n'
            '    {"action": "none"}\n'
            "  ],\n"
            '  "policy_effects": {"require_ticket_approval": true|false|null, '
            '"can_delegate": true|false|null}\n'
            "}\n"
        )
        examples = (
            "Examples of STANDING RULES (add) — persistent behavior for all future colleague chats:\n"
            '- "if someone asks to make a ticket, put them on hold and text me to confirm"\n'
            '  → add rule + require_ticket_approval:true + can_delegate:false\n'
            '- "tell people wanting Copilot Studio generative AI access to request on myaccess"\n'
            '  → add rule about myaccess (no policy flag change)\n'
            '- "don\'t assign anyone tickets while I\'m away"\n'
            '  → add rule + can_delegate:false\n\n'
            "Examples of NOT rules (operations=[] action none):\n"
            '- "what happened in my absence?" → information_query\n'
            '- "what did the intern say?" → information_query\n'
            '- "go absent" / "approve TA-1" → operational_command\n'
            '- "thanks" / "ok" → casual_chat\n\n'
            "When adding a rule, rewrite rule_text as a clear standing instruction the twin "
            "follows in EVERY colleague conversation. Include policy_tags when the rule "
            "implies ticket-approval workflow or delegation restrictions."
        )
        prompt = (
            f"{schema}\n\n{examples}\n\n{rules_block}\n\n"
            f"Owner message:\n{user_message.strip()}\n"
        )
        if assistant_reply:
            prompt += f"\nTwin reply (context only, do not treat as a new rule):\n{assistant_reply[:400]}\n"

        client = _make_client()
        response = client.chat.completions.create(
            model=_model_name(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the policy brain for a manager's digital twin at work. "
                        "Your job is to distinguish durable STANDING RULES (how the twin "
                        "must behave in all future colleague conversations) from one-off "
                        "QUESTIONS, STATUS CHECKS, APPROVAL COMMANDS, or casual chat. "
                        "Think step by step: is the owner setting ongoing behavior, or "
                        "asking/ordering something for right now? "
                        "Only extract standing rules. Never add rules for questions like "
                        "'what happened' or commands like 'approve TA-1' or 'go absent'. "
                        "When a rule says notify/confirm/text/ping the owner before creating "
                        "tickets, set require_ticket_approval:true in policy_tags and "
                        "policy_effects."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        content = (response.choices[0].message.content or "").strip()
        return _parse_llm_classification(content)
    except Exception as e:
        logger.debug("owner rule LLM classify failed: %s", e)
        return None


def _llm_derive_policy(rules: list[dict]) -> dict[str, Optional[bool]] | None:
    """Ask LLM to read all standing rules and derive policy flags."""
    if not rules:
        return {"require_ticket_approval": False, "can_delegate": True}
    try:
        from agent_network.agent.llm_router import _make_client, _model_name

        lines = [f"[{r['id']}] {r['rule_text']}" for r in rules]
        prompt = (
            "Given these standing rules for a manager's digital twin, determine policy:\n\n"
            + "\n".join(lines)
            + "\n\nReturn ONLY JSON:\n"
            '{"require_ticket_approval": true|false, "can_delegate": true|false, '
            '"reasoning": "brief"}\n'
            "require_ticket_approval=true when ANY rule says to notify/confirm/text/ping "
            "the owner before creating tickets for colleagues, or put ticket requests on hold.\n"
            "can_delegate=false when ANY rule forbids assigning/delegating/creating tickets "
            "for colleagues without owner approval."
        )
        client = _make_client()
        response = client.chat.completions.create(
            model=_model_name(),
            messages=[
                {
                    "role": "system",
                    "content": "Derive twin policy flags from owner standing rules. JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        content = (response.choices[0].message.content or "").strip()
        cleaned = _strip_json_fence(content)
        obj = json.loads(cleaned)
        if not isinstance(obj, dict):
            return None
        return {
            "require_ticket_approval": obj.get("require_ticket_approval"),
            "can_delegate": obj.get("can_delegate"),
        }
    except Exception as e:
        logger.debug("derive policy LLM failed: %s", e)
        return None


def _parse_llm_classification(text: str) -> OwnerRuleClassification | None:
    cleaned = _strip_json_fence(text)
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None

    ops = obj.get("operations")
    if not isinstance(ops, list) or not ops:
        ops = [{"action": "none"}]

    normalized: list[dict[str, Any]] = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        action = str(op.get("action", "none")).lower().strip()
        if action not in ("add", "update", "revoke", "none"):
            continue
        entry: dict[str, Any] = {"action": action}
        if action in ("add", "update"):
            rt = str(op.get("rule_text", "")).strip()
            if rt:
                entry["rule_text"] = rt
            tags = op.get("policy_tags")
            if isinstance(tags, dict):
                entry["policy_tags"] = {
                    k: bool(v)
                    for k, v in tags.items()
                    if k in ("require_ticket_approval", "can_delegate") and v is not None
                }
        if action in ("update", "revoke") and op.get("rule_id") is not None:
            entry["rule_id"] = int(op["rule_id"])
        normalized.append(entry)

    if not normalized:
        normalized = [{"action": "none"}]

    policy_effects = obj.get("policy_effects")
    if not isinstance(policy_effects, dict):
        policy_effects = {}

    kind = str(obj.get("message_kind", "unknown"))
    reasoning = str(obj.get("reasoning", ""))

    # Safety: queries/commands should not mutate rules even if model errs
    if kind in ("information_query", "operational_command", "casual_chat"):
        normalized = [{"action": "none"}]

    return OwnerRuleClassification(
        operations=normalized,
        message_kind=kind,
        reasoning=reasoning,
        policy_effects={
            k: policy_effects.get(k)
            for k in ("require_ticket_approval", "can_delegate")
            if k in policy_effects
        },
    )


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned


def _heuristic_policy_effects(
    user_message: str, ops: list[dict[str, Any]]
) -> dict[str, Optional[bool]]:
    from agent_network.ticket_approval import (
        rule_requires_ticket_approval,
        wants_ticket_hold_and_notify,
    )

    effects: dict[str, Optional[bool]] = {}
    lower = user_message.lower()
    if wants_no_delegation(lower):
        effects["can_delegate"] = False
    if rule_requires_ticket_approval(user_message) or wants_ticket_hold_and_notify(
        user_message
    ):
        effects["require_ticket_approval"] = True
    for op in ops:
        tags = op.get("policy_tags") or {}
        if tags.get("require_ticket_approval"):
            effects["require_ticket_approval"] = True
        if tags.get("can_delegate") is False:
            effects["can_delegate"] = False
    return effects


def _heuristic_classify(
    user_message: str,
    active_rules: list[dict],
) -> list[dict[str, Any]]:
    text = user_message.strip()
    lower = text.lower()

    if _is_revoke_intent(lower):
        match = _match_rule_for_revoke(lower, active_rules)
        if match:
            return [{"action": "revoke", "rule_id": match["id"]}]
        return [{"action": "none"}]

    if _is_update_intent(lower):
        match = _match_rule_for_update(lower, active_rules)
        new_text = _extract_update_text(text, lower)
        if match and new_text:
            return [
                {
                    "action": "update",
                    "rule_id": match["id"],
                    "rule_text": new_text,
                    "policy_tags": _heuristic_policy_effects(new_text, []),
                }
            ]
        if new_text:
            return [
                {
                    "action": "add",
                    "rule_text": new_text,
                    "policy_tags": _heuristic_policy_effects(new_text, []),
                }
            ]

    rule_text = _extract_rule_candidate(text, lower)
    if rule_text:
        tags = _heuristic_policy_effects(rule_text, [])
        op: dict[str, Any] = {"action": "add", "rule_text": rule_text}
        if tags:
            op["policy_tags"] = tags
        return [op]

    return [{"action": "none"}]


def _is_revoke_intent(lower: str) -> bool:
    return any(cue in lower for cue in _REVOKE_CUES)


def _is_update_intent(lower: str) -> bool:
    return any(cue in lower for cue in _UPDATE_CUES)


def _extract_rule_candidate(text: str, lower: str) -> str | None:
    if is_owner_instruction_message(lower):
        extracted = extract_instruction_text(text, lower)
        return (extracted or text).strip()
    if wants_no_delegation(lower):
        return (
            "Do not assign, create, or delegate tickets to colleagues "
            "while the owner is away unless the owner explicitly directs it."
        )
    if re.search(r"\bwhen\b.+\bask", lower) or "if someone asks" in lower:
        return text.strip()
    if any(
        topic in lower
        for topic in (
            "myaccess",
            "my access",
            "copilot studio",
            "copilot",
            "generative ai",
            "gen ai",
        )
    ) and any(
        verb in lower
        for verb in ("tell them", "direct them", "point them", "send them", "ask them to")
    ):
        return text.strip()
    if "in my absence" in lower or "while i'm away" in lower or "while im away" in lower:
        if any(
            w in lower
            for w in ("tell them", "say ", "explain", "don't", "do not", "never", "always")
        ):
            return text.strip()
    if lower.startswith("instructions:") or lower.startswith("rule:"):
        return text.split(":", 1)[-1].strip() or text.strip()
    return None


def _extract_update_text(text: str, lower: str) -> str | None:
    for cue in _UPDATE_CUES:
        if cue in lower:
            idx = lower.index(cue)
            rest = text[idx + len(cue) :].strip(" :.-")
            if rest:
                return rest
    if "instead" in lower:
        parts = re.split(r"\binstead\b", text, maxsplit=1, flags=re.I)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip(" ,:-")
    return text.strip()


def _match_rule_for_revoke(lower: str, active_rules: list[dict]) -> dict | None:
    if not active_rules:
        return None
    keywords = _topic_keywords(lower)
    best: dict | None = None
    best_score = 0
    for rule in active_rules:
        score = _keyword_overlap(keywords, rule["rule_text"].lower())
        if score > best_score:
            best_score = score
            best = rule
    if best and best_score >= 1:
        return best
    if len(active_rules) == 1:
        return active_rules[0]
    return None


def _match_rule_for_update(lower: str, active_rules: list[dict]) -> dict | None:
    return _match_rule_for_revoke(lower, active_rules)


def _topic_keywords(lower: str) -> set[str]:
    stop = {
        "that",
        "this",
        "rule",
        "forget",
        "remove",
        "delete",
        "cancel",
        "ignore",
        "the",
        "about",
        "when",
        "they",
        "them",
        "please",
    }
    words = re.findall(r"[a-z0-9]+", lower)
    return {w for w in words if len(w) > 2 and w not in stop}


def _keyword_overlap(keywords: set[str], hay: str) -> int:
    if not keywords:
        return 0
    return sum(1 for k in keywords if k in hay)
