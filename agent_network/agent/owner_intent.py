"""Detect and apply owner natural-language stand-in directives."""

from __future__ import annotations

import re
from typing import Optional

from agent_network.models import TwinStandInPolicy
from agent_network.standin_policy import get_policy, set_instructions, set_policy

_INSTRUCTION_CUES = (
    "keep this in mind",
    "remember this",
    "remember that",
    "remember to",
    "make sure",
    "don't assign",
    "do not assign",
    "dont assign",
    "don't delegate",
    "do not delegate",
    "dont delegate",
    "never assign",
    "never delegate",
    "only i will assign",
    "only i'll assign",
    "ill assign tickets only",
    "i'll assign tickets only",
    "assign tickets only by myself",
    "instructions:",
    "when you're standing in",
    "when you stand in",
    "while i'm away",
    "while im away",
    "in my absence",
    "when i'm away",
    "when im away",
    "when i am away",
    "tell them",
    "direct them",
    "point them",
    "myaccess",
    "my access",
)

_ACTIVITY_CUES = (
    "what happened",
    "anything happen",
    "anything happened",
    "did you assign",
    "did anyone get assigned",
    "did you delegate",
    "what did you do",
    "activity while away",
    "absence summary",
    "while i was away",
    "when i was away",
)

_NO_DELEGATE_CUES = (
    "don't assign",
    "do not assign",
    "dont assign",
    "not to assign",
    "not assign any",
    "no assigning",
    "without assigning",
    "shouldn't assign",
    "should not assign",
    "don't delegate",
    "do not delegate",
    "dont delegate",
    "not to delegate",
    "never assign",
    "never delegate",
    "won't assign",
    "will not assign",
    "only i will assign",
    "only i'll assign",
    "assign tickets only by myself",
    "ill assign tickets only",
    "i'll assign tickets only",
)


def is_owner_instruction_message(lower: str) -> bool:
    return any(cue in lower for cue in _INSTRUCTION_CUES)


def is_owner_activity_query(lower: str) -> bool:
    return any(cue in lower for cue in _ACTIVITY_CUES)


def is_delegate_activity_query(lower: str) -> bool:
    return any(
        cue in lower
        for cue in (
            "did you assign",
            "did anyone get assigned",
            "did you delegate",
            "assign anyone tickets",
            "assign any tickets",
        )
    )


_COLLEAGUE_CONVERSATION_PATTERNS = (
    r"what did .+\s(say|tell|ask|mention|message)",
    r"what has .+\s(said|told|asked)",
    r"what have .+\s(said|told|asked)",
    r"who (said|told|asked|messaged|pinged|reached out)",
    r"what (did|have) (the )?(intern|assignee|observer|colleague|demo)",
    r"conversations? with",
    r"said to you",
    r"told you",
    r"asked you",
    r"messaged you",
    r"talked to you",
    r"chatted with you",
    r"what were (they|people|colleagues)",
    r"what was .+ asking",
    r"repeat what",
    r"summarize (the )?conversation",
)


def is_colleague_conversation_query(lower: str) -> bool:
    """Owner wants transcripts from colleague stand-in chats (on-demand fetch)."""
    if is_owner_activity_query(lower) or is_delegate_activity_query(lower):
        return False
    return any(re.search(pat, lower) for pat in _COLLEAGUE_CONVERSATION_PATTERNS)


def resolve_colleague_requester_from_message(
    text: str, twin_employee_id: str = ""
) -> Optional[str]:
    """
    Identify which colleague's stand-in chat the owner is asking about.
    Returns employee_id or None if no specific person is named.
    """
    from agent_network.registry import (
        DEMO_ASSIGNEE_ID,
        DEMO_INTERN_ID,
        DEMO_OBSERVER_ID,
        SAMPLE_EMPLOYEES,
        employee_by_name,
    )

    lower = (text or "").lower()
    if not lower.strip():
        return None

    aliases = {
        "intern": DEMO_INTERN_ID,
        "demo intern": DEMO_INTERN_ID,
        "assignee": DEMO_ASSIGNEE_ID,
        "demo assignee": DEMO_ASSIGNEE_ID,
        "engineer": DEMO_ASSIGNEE_ID,
        "observer": DEMO_OBSERVER_ID,
        "demo observer": DEMO_OBSERVER_ID,
    }
    for alias, emp_id in sorted(aliases.items(), key=lambda x: -len(x[0])):
        if alias in lower and emp_id != twin_employee_id:
            return emp_id

    for emp in SAMPLE_EMPLOYEES:
        if emp.employee_id == twin_employee_id:
            continue
        name_lower = emp.name.lower()
        if name_lower in lower:
            return emp.employee_id
        # "the intern" partial — first name token
        first = name_lower.split()[-1] if " " in name_lower else name_lower
        if len(first) > 3 and re.search(rf"\b{re.escape(first)}\b", lower):
            return emp.employee_id

    # Try free-form name lookup on significant phrases
    for match in re.finditer(r"\b(demo\s+\w+|\w+)\b", lower):
        fragment = match.group(1).strip()
        if fragment in ("what", "did", "the", "say", "tell", "you", "who", "that"):
            continue
        emp = employee_by_name(fragment)
        if emp and emp.employee_id != twin_employee_id:
            return emp.employee_id

    return None


def wants_no_delegation(lower: str) -> bool:
    return any(cue in lower for cue in _NO_DELEGATE_CUES)


def extract_instruction_text(text: str, lower: str) -> str:
    if lower.startswith("instructions:"):
        return text.split(":", 1)[1].strip()
    cleaned = text.strip()
    cleaned = re.sub(
        r"^(okay|ok|yes|sure|please|thanks)[.,!\s]+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


def apply_stand_in_flags_from_owner_text(employee_id: str, text: str) -> bool:
    """
    Flip structured policy flags when owner briefing text implies them.
    Returns True if policy changed.
    """
    from agent_network.ticket_approval import wants_ticket_hold_and_notify

    lower = (text or "").lower()
    changed = False
    policy = get_policy(employee_id)
    if wants_no_delegation(lower):
        if policy.can_delegate:
            policy.can_delegate = False
            changed = True
    if wants_ticket_hold_and_notify(text) or (
        "ticket" in lower and any(p in lower for p in ("text me", "notify me", "confirm"))
    ):
        if not policy.require_ticket_approval:
            policy.require_ticket_approval = True
            changed = True
    if changed:
        set_policy(employee_id, policy)
    return changed


def apply_owner_instruction(employee_id: str, text: str, lower: str) -> str:
    """Persist instructions and policy flags from natural owner language."""
    instr = extract_instruction_text(text, lower)
    if not instr:
        return "Tell me how to act while you're away — e.g. don't assign tickets without asking me."

    policy = get_policy(employee_id)
    if wants_no_delegation(lower):
        policy.can_delegate = False

    policy.instructions = instr
    set_policy(employee_id, policy)
    set_instructions(employee_id, instr)

    lines = [
        "Got it — I'll follow this while you're away:",
        f'"{instr}"',
    ]
    if not policy.can_delegate:
        lines.append(
            "While you're away, I won't assign tickets to colleagues on my own — "
            "but you can always direct me to assign or delegate anytime."
        )
    return "\n".join(lines)
