"""Integration tests for unified talk + act routing."""

import os
from unittest.mock import patch

from agent_network.agent.twin_chat import TwinChatSession
from agent_network.agent.work_actions import detect_work_action, WorkAction
from agent_network.mcp import reset_toolset
from agent_network.mcp.mock_tools import MockToolSet
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID, set_employee_absent
from agent_network.runtime import reset_runtime
from agent_network.standin_policy import get_policy, set_policy
from agent_network import owner_instruction_memory
from agent_network import ticket_approval


def _clear_approval_policy():
    ticket_approval.clear_all()
    ticket_approval.reset_ticket_approval_memory()
    owner_instruction_memory.clear_all()
    owner_instruction_memory.reset_instruction_memory()
    policy = get_policy(DEMO_MANAGER_ID)
    policy.require_ticket_approval = False
    set_policy(DEMO_MANAGER_ID, policy)


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_create_ticket_detected_and_returns_id():
    _clear_approval_policy()
    set_employee_absent(DEMO_MANAGER_ID, True)
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        session.employee.is_absent = True
        msg = (
            "my manager assigned me the task of creating a sprint planner, "
            "can you make me a ticket for it?"
        )
        assert detect_work_action(session, msg) == WorkAction.CREATE_TICKET
        reply = session.handle(msg)
        assert "JIRA-" in reply


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_list_tickets_is_work_not_chat():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        session.employee.is_absent = True
        assert detect_work_action(session, "list my tickets") == WorkAction.LIST_TICKETS
        reply = session.handle("list my tickets")
        assert "JIRA-" in reply or "ticket" in reply.lower()
        assert "commands:" not in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_vague_help_is_chat_not_work():
    reset_toolset()
    reset_runtime()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    session.employee.is_absent = True
    assert detect_work_action(session, "hi I need help") is None
    reply = session.handle("hi I need help")
    assert "JIRA-" not in reply
    assert "commands:" not in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_describing_assigned_work_is_talk_not_tool():
    reset_toolset()
    reset_runtime()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    session.employee.is_absent = True
    msg = "my manager assigned me the task of creating a sprint planner"
    assert detect_work_action(session, msg) is None
    reply = session.handle(msg)
    assert "JIRA-" not in reply
    assert "commands:" not in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_what_is_question_is_talk_not_ticket_lookup():
    reset_toolset()
    reset_runtime()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    session.employee.is_absent = True
    msg = "what is a sprint planner"
    assert detect_work_action(session, msg) is None
    reply = session.handle(msg)
    assert "JIRA-" not in reply


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_create_ticket_blocked_when_owner_forbids_assignment():
    from agent_network.standin_policy import get_policy, reset_standin_policies

    reset_standin_policies()
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        owner.handle("not to assign any tickets in my absence")
        assert get_policy(DEMO_MANAGER_ID).can_delegate is False

        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        reply = intern.handle("can you make me a ticket for sprint planner?")
        assert "JIRA-" not in reply
        assert "assign" in reply.lower()
        reset_standin_policies()
