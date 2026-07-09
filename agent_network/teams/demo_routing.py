"""
Teams demo routing: pick twin + requester persona, isolate memory per pair.

Production: TEAMS_USER_MAP fixes who you are; talk to <name> picks the twin.
Demo (TEAMS_DEMO_MODE): one real user can impersonate demo roles via chat commands.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from agent_network import memory
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.registry import (
    DEMO_MANAGER_ID,
    SAMPLE_EMPLOYEES,
    employee_by_id,
    employee_by_name,
    employee_display_name,
)


def teams_demo_mode() -> bool:
    explicit = os.getenv("TEAMS_DEMO_MODE", "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    if explicit in ("0", "false", "no", "off"):
        return False
    # Emulator / local testing without Azure user mapping
    return os.getenv("BOT_EMULATOR_MODE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def default_twin_id() -> str:
    return os.getenv("DEFAULT_TWIN_ID", DEMO_MANAGER_ID)


def session_memory_id(twin_employee_id: str, requester_employee_id: Optional[str]) -> str:
    """Same key as Streamlit: twin + requester → isolated memory thread."""
    if (
        requester_employee_id
        and requester_employee_id == twin_employee_id
    ):
        return memory.owner_coordination_conversation_id(twin_employee_id)
    if requester_employee_id:
        return memory.conversation_id_for_colleague(
            twin_employee_id, requester_employee_id
        )
    return f"{twin_employee_id}:anon"


@dataclass
class TeamsDemoState:
    """Per Teams channel (1:1 chat id): which twin and which demo persona."""

    twin_employee_id: str = DEMO_MANAGER_ID
    requester_employee_id: Optional[str] = None
    requester_override: bool = False


def resolve_employee_from_phrase(phrase: str) -> Optional[str]:
    phrase = (phrase or "").strip()
    if not phrase:
        return None
    emp = employee_by_id(phrase)
    if emp:
        return emp.employee_id
    emp = employee_by_name(phrase)
    if emp:
        return emp.employee_id
    aliases = {
        "manager": DEMO_MANAGER_ID,
        "demo manager": DEMO_MANAGER_ID,
        "intern": "emp-intern",
        "demo intern": "emp-intern",
        "assignee": "emp-assignee",
        "demo assignee": "emp-assignee",
        "observer": "emp-observer",
        "demo observer": "emp-observer",
    }
    return aliases.get(phrase.lower())


def demo_roster_help() -> str:
    names = ", ".join(e.name for e in SAMPLE_EMPLOYEES)
    return (
        "**Demo session commands** (Teams demo mode)\n\n"
        f"Roster: {names}\n\n"
        "**Pick whose twin:**\n"
        "  • `talk to demo manager`\n"
        "  • `talk to demo intern`\n\n"
        "**Pick who you are** (changes behaviour + memory):\n"
        "  • `act as demo manager` — owner (policy, activity recap)\n"
        "  • `act as demo assignee` — colleague (tickets, delegation)\n"
        "  • `act as demo intern`\n\n"
        "**Status:** `session` — shows twin, persona, memory thread\n\n"
        "Each twin + persona pair has its own chat memory, same as the Streamlit demo."
    )


def parse_demo_command(
    text: str,
    state: TeamsDemoState,
    *,
    mapped_requester_id: Optional[str],
) -> Optional[str]:
    """
    Handle talk-to / act-as / session commands. Returns reply text or None to continue.
    """
    lower = (text or "").strip().lower()
    if not lower:
        return None

    if lower in ("help demo", "demo help", "demo commands"):
        return demo_roster_help()

    if lower in ("session", "who am i", "status"):
        return format_session_status(state)

    if lower.startswith("talk to ") or lower.startswith("switch to "):
        target_name = text.split("to", 1)[1].strip()
        emp_id = resolve_employee_from_phrase(target_name)
        if not emp_id:
            return f"I don't know a twin named '{target_name}'. Try: demo manager, demo intern."
        state.twin_employee_id = emp_id
        twin = employee_by_id(emp_id)
        label = twin.name if twin else emp_id
        session = build_session(state)
        return (
            f"You're now talking to **{label}'s twin**.\n"
            f"Acting as: **{session.requester.name if session.requester else 'unknown'}**.\n"
            f"Memory thread: `{session.conversation_id}`\n\n"
            f"{session.greeting()}"
        )

    if teams_demo_mode() and lower.startswith("act as "):
        role_phrase = text[7:].strip()
        emp_id = resolve_employee_from_phrase(role_phrase)
        if not emp_id:
            return (
                f"I don't know the role '{role_phrase}'. "
                "Try: act as demo manager, act as demo assignee, act as demo intern."
            )
        state.requester_employee_id = emp_id
        state.requester_override = True
        emp = employee_by_id(emp_id)
        twin = employee_by_id(state.twin_employee_id)
        session = build_session(state)
        owner = session.is_owner_session()
        mode = "owner coordination" if owner else "colleague stand-in"
        return (
            f"You're now **{emp.name if emp else emp_id}** talking to "
            f"**{twin.name if twin else state.twin_employee_id}'s twin** ({mode}).\n"
            f"Memory thread: `{session.conversation_id}`\n\n"
            f"{session.greeting()}"
        )

    # Apply Teams user map when demo has not overridden persona
    if not state.requester_override and mapped_requester_id:
        state.requester_employee_id = mapped_requester_id

    return None


def format_session_status(state: TeamsDemoState) -> str:
    twin = employee_by_id(state.twin_employee_id)
    requester = employee_by_id(state.requester_employee_id) if state.requester_employee_id else None
    mem_id = session_memory_id(state.twin_employee_id, state.requester_employee_id)
    turns = memory.history_count(mem_id)
    owner = (
        state.requester_employee_id
        and state.requester_employee_id == state.twin_employee_id
    )
    return (
        "**Current demo session**\n"
        f"• Twin: {twin.name if twin else state.twin_employee_id}\n"
        f"• You are: {requester.name if requester else '(not set — use act as ...)'}\n"
        f"• Mode: {'owner' if owner else 'colleague'}\n"
        f"• Memory thread: `{mem_id}` ({turns} turn(s))\n"
        f"• Demo mode: {'on' if teams_demo_mode() else 'off'}"
    )


def build_session(state: TeamsDemoState) -> TwinChatSession:
    return TwinChatSession(
        twin_employee_id=state.twin_employee_id,
        requester_employee_id=state.requester_employee_id,
        conversation_id=session_memory_id(
            state.twin_employee_id, state.requester_employee_id
        ),
    )


def initial_state(mapped_requester_id: Optional[str]) -> TeamsDemoState:
    twin = default_twin_id()
    if not employee_by_id(twin):
        twin = DEMO_MANAGER_ID
    return TeamsDemoState(
        twin_employee_id=twin,
        requester_employee_id=mapped_requester_id,
        requester_override=False,
    )
