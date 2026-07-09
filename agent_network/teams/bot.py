"""
Teams bot: routes Teams chat messages to the right digital twin.

Demo mode (TEAMS_DEMO_MODE / Emulator): use chat commands to switch twin and persona:
  talk to demo manager | act as demo assignee | session

Memory is keyed by twin+requester (same as Streamlit), not the raw Teams conversation id.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from agent_network.agent.twin_chat import TwinChatSession
from agent_network.config import default_requester_id
from agent_network.registry import (
    DEMO_MANAGER_ID,
    employee_by_email,
    employee_by_id,
    employee_by_name,
)
from agent_network.teams.demo_routing import (
    TeamsDemoState,
    build_session,
    initial_state,
    parse_demo_command,
    teams_demo_mode,
)

logger = logging.getLogger(__name__)


def _teams_user_map() -> dict[str, str]:
    raw = os.getenv("TEAMS_USER_MAP", "").strip()
    if not raw:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in json.loads(raw).items()}
    except json.JSONDecodeError:
        logger.warning("TEAMS_USER_MAP is not valid JSON")
        return {}


def resolve_requester_id(
    aad_object_id: Optional[str], name: Optional[str], email: Optional[str]
) -> Optional[str]:
    mapping = _teams_user_map()
    for key in (aad_object_id, email, name):
        if key and key.lower() in mapping:
            return mapping[key.lower()]
    if email:
        emp = employee_by_email(email)
        if emp:
            return emp.employee_id
    if name:
        emp = employee_by_name(name)
        if emp:
            return emp.employee_id
    fallback = default_requester_id()
    return fallback or None


def default_twin_id() -> str:
    return os.getenv("DEFAULT_TWIN_ID", DEMO_MANAGER_ID)


def build_bot():
    """Construct the Teams ActivityHandler (imports botbuilder lazily)."""
    from botbuilder.core import ActivityHandler, TurnContext
    from botbuilder.schema import ChannelAccount  # noqa: F401

    class TwinTeamsBot(ActivityHandler):
        def __init__(self) -> None:
            # Teams channel conversation id -> demo session state
            self._sessions: dict[str, TeamsDemoState] = {}

        def _get_state(
            self, channel_id: str, mapped_requester_id: Optional[str]
        ) -> TeamsDemoState:
            if channel_id not in self._sessions:
                self._sessions[channel_id] = initial_state(mapped_requester_id)
            state = self._sessions[channel_id]
            if not state.requester_override and mapped_requester_id:
                state.requester_employee_id = mapped_requester_id
            return state

        async def on_message_activity(self, turn_context: "TurnContext"):
            activity = turn_context.activity
            text = (activity.text or "").strip()
            channel_id = activity.conversation.id if activity.conversation else "teams"

            frm = activity.from_property
            aad = getattr(frm, "aad_object_id", None) if frm else None
            name = getattr(frm, "name", None) if frm else None
            email = None
            if frm:
                props = getattr(frm, "additional_properties", None) or {}
                email = props.get("email") or props.get("userPrincipalName")

            mapped_requester = resolve_requester_id(aad, name, email)
            state = self._get_state(channel_id, mapped_requester)

            demo_reply = parse_demo_command(
                text, state, mapped_requester_id=mapped_requester
            )
            if demo_reply is not None:
                await turn_context.send_activity(demo_reply)
                return

            if not state.twin_employee_id or not employee_by_id(state.twin_employee_id):
                state.twin_employee_id = default_twin_id() or DEMO_MANAGER_ID

            session = build_session(state)
            if not text and teams_demo_mode():
                reply = (
                    f"{session.greeting()}\n\n"
                    "Demo tip: type `help demo` to switch twin or persona."
                )
            else:
                reply = session.handle(text) if text else session.greeting()
            await turn_context.send_activity(reply)

        async def on_members_added_activity(self, members_added, turn_context: "TurnContext"):
            for member in members_added:
                if member.id != turn_context.activity.recipient.id:
                    channel_id = (
                        turn_context.activity.conversation.id
                        if turn_context.activity.conversation
                        else "teams"
                    )
                    mapped = resolve_requester_id(None, getattr(member, "name", None), None)
                    state = self._get_state(channel_id, mapped)
                    session = build_session(state)
                    greeting = session.greeting()
                    if teams_demo_mode():
                        greeting += (
                            "\n\n**Demo mode** — type `help demo` to pick whose twin "
                            "and which persona (act as demo manager / assignee / intern)."
                        )
                    await turn_context.send_activity(greeting)

    return TwinTeamsBot()
