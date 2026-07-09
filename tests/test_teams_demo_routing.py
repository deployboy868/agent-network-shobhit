"""Teams demo routing: twin + requester selection and memory thread keys."""

import os
from unittest.mock import patch

from agent_network import memory
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_INTERN_ID, DEMO_MANAGER_ID
from agent_network.teams.demo_routing import (
    TeamsDemoState,
    build_session,
    parse_demo_command,
    session_memory_id,
)


def test_session_memory_id_matches_streamlit():
    assert session_memory_id(DEMO_MANAGER_ID, DEMO_MANAGER_ID) == "emp-manager:emp-manager"
    assert session_memory_id(DEMO_MANAGER_ID, DEMO_INTERN_ID) == "emp-manager:emp-intern"
    assert session_memory_id(DEMO_INTERN_ID, DEMO_ASSIGNEE_ID) == "emp-intern:emp-assignee"


@patch.dict(os.environ, {"TEAMS_DEMO_MODE": "true"})
def test_talk_to_switches_twin():
    memory.reset_memory()
    state = TeamsDemoState(twin_employee_id=DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    reply = parse_demo_command("talk to demo intern", state, mapped_requester_id=None)
    assert reply is not None
    assert state.twin_employee_id == DEMO_INTERN_ID
    assert "Demo Intern" in reply


@patch.dict(os.environ, {"TEAMS_DEMO_MODE": "true", "LLM_PROVIDER": "none"})
def test_act_as_switches_requester_and_memory_thread():
    memory.reset_memory()
    state = TeamsDemoState(twin_employee_id=DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    memory.remember("emp-manager:emp-manager", "user", "owner message one", DEMO_MANAGER_ID)

    reply = parse_demo_command("act as demo assignee", state, mapped_requester_id=None)
    assert reply is not None
    assert state.requester_employee_id == DEMO_ASSIGNEE_ID
    assert state.requester_override is True
    assert "colleague" in reply.lower() or "Demo Assignee" in reply

    assignee_session = build_session(state)
    assert assignee_session.conversation_id == "emp-manager:emp-assignee"
    assert not assignee_session.is_owner_session()
    assert memory.history_count("emp-manager:emp-manager") >= 1
    assert memory.history_count("emp-manager:emp-assignee") == 0


@patch.dict(os.environ, {"TEAMS_DEMO_MODE": "true"})
def test_session_command_shows_status():
    state = TeamsDemoState(
        twin_employee_id=DEMO_MANAGER_ID,
        requester_employee_id=DEMO_ASSIGNEE_ID,
    )
    reply = parse_demo_command("session", state, mapped_requester_id=None)
    assert reply is not None
    assert "Demo Manager" in reply
    assert "Demo Assignee" in reply
    assert "emp-manager:emp-assignee" in reply
