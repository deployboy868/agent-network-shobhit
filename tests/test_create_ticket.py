"""Tests for create-ticket-for-requester (vs delegate)."""

import json
import os
from unittest.mock import patch

from agent_network.agent.llm_tool_guards import (
    user_wants_create_ticket_for_self,
    user_wants_delegate,
)
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.mcp import reset_toolset
from agent_network.mcp.mock_tools import MockToolSet
from agent_network.mcp_server.tools_registry import call_tool
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID, set_employee_absent
from agent_network.runtime import reset_runtime
from agent_network.standin_policy import get_policy, set_policy
from agent_network import ticket_approval
from agent_network import owner_instruction_memory
from agent_network.models import TwinStandInPolicy


def _clear_approval_policy():
    ticket_approval.clear_all()
    ticket_approval.reset_ticket_approval_memory()
    owner_instruction_memory.clear_all()
    owner_instruction_memory.reset_instruction_memory()
    policy = get_policy(DEMO_MANAGER_ID)
    policy.require_ticket_approval = False
    set_policy(DEMO_MANAGER_ID, policy)


def test_create_for_self_vs_delegate():
    msg = "can you make me a ticket for the Sprint Planner?"
    assert user_wants_create_ticket_for_self(msg)
    assert not user_wants_delegate(msg)

    long_msg = (
        "my manager assigned me the task of creating a sprint planner, "
        "can you make me a ticket for it?"
    )
    assert user_wants_create_ticket_for_self(long_msg)

    assert user_wants_create_ticket_for_self("please create a ticket for sprint planner")

    delegate_msg = "delegate handbook fix to assignee"
    assert user_wants_delegate(delegate_msg)
    assert not user_wants_create_ticket_for_self(delegate_msg)


def test_agent_mode_skips_create_ticket_keyword_guard():
    from agent_network.agent.llm_tool_guards import guard_and_prepare_tool

    _clear_approval_policy()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    session.employee.is_absent = True
    args, blocked = guard_and_prepare_tool(
        session,
        "twin_create_ticket_for_requester",
        {"title": "Sprint Planner"},
        "yeah track that sprint planner work for me",
        agent_mode=True,
    )
    assert blocked is None
    assert args["title"] == "Sprint Planner"
    assert args["requester_employee_id"] == DEMO_INTERN_ID


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_create_ticket_tool_returns_jira_id():
    _clear_approval_policy()
    set_employee_absent(DEMO_MANAGER_ID, True)
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            result = call_tool(
                "twin_create_ticket_for_requester",
                {
                    "twin_employee_id": DEMO_MANAGER_ID,
                    "requester_employee_id": DEMO_INTERN_ID,
                    "title": "Sprint Planner",
                    "description": "Build sprint planning tool",
                },
            )
            assert not result.get("isError")
            data = json.loads(result["content"][0]["text"])
            assert data["ticket_id"].startswith("JIRA-")
            assert data["assignee_employee_id"] == DEMO_INTERN_ID


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_intern_ask_create_ticket_shows_id_in_chat():
    _clear_approval_policy()
    set_employee_absent(DEMO_MANAGER_ID, True)
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        session.employee.is_absent = True
        reply = session.handle(
            "my manager assigned me the task of creating a sprint planner, "
            "can you make me a ticket for it?"
        )
        assert "JIRA-" in reply
        assert "ana" not in reply.lower()
        assert "sprint planner" in reply.lower()
