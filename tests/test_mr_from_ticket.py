"""Tests for MR-from-ticket sub-agent and keyword routing."""

from __future__ import annotations

import os
from unittest.mock import patch

from agent_network.agent.action_reasoning import user_wants_implement_ticket
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.mcp import get_toolset, reset_toolset
from agent_network.mcp.mock_tools import MockToolSet
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID
from agent_network.models import TaskStatus
from agent_network.runtime import reset_runtime
from agent_network.workers.mr_from_ticket import generate_task_artifact


def test_user_wants_implement_ticket():
    assert user_wants_implement_ticket("implement LST-12345")
    assert user_wants_implement_ticket("generate MR for LST-99")
    assert not user_wants_implement_ticket("list merge requests")
    assert not user_wants_implement_ticket("implement the login page")


def test_generate_task_artifact_fallback_without_llm():
    with patch.dict(os.environ, {"LLM_PROVIDER": "none"}, clear=False):
        artifact = generate_task_artifact(
            "LST-1",
            "[Agent-Network-TEST] Demo task",
            "Add docs for twin stand-in.",
        )
    assert artifact["file_path"].endswith("LST-1.md")
    assert "LST-1" in artifact["file_content"]
    assert artifact["summary"]


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_implement_ticket_mr_mock():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    ticket = mock.jira.create_ticket(
        title="[Agent-Network-TEST] Wire MR sub-agent",
        description="Document the flow.",
        reporter_id=DEMO_MANAGER_ID,
    )
    mock.jira.assign_ticket(ticket.ticket_id, DEMO_MANAGER_ID)
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            get_toolset()
            session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
            reply = session.handle(f"implement {ticket.ticket_id}")
            assert "merge request" in reply.lower() or "mr" in reply.lower()
            assert "gitlab.example.com" in reply.lower() or ticket.ticket_id in reply


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_implement_mr_blocked_for_colleague():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            session = TwinChatSession(
                DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID
            )
            reply = session.handle("implement LST-12345")
            assert "only" in reply.lower() or "own twin" in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_implement_mr_blocked_without_gitlab_skill():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            session = TwinChatSession(DEMO_INTERN_ID, requester_employee_id=DEMO_INTERN_ID)
            reply = session.handle("implement LST-12345")
            assert "gitlab" in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_implement_mr_blocked_for_closed_ticket():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    ticket = mock.jira.create_ticket(
        title="[Agent-Network-TEST] Closed ticket",
        description="Already done.",
        reporter_id=DEMO_MANAGER_ID,
    )
    mock.jira.assign_ticket(ticket.ticket_id, DEMO_MANAGER_ID)
    mock.jira.update_status(ticket.ticket_id, TaskStatus.DONE.value)
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
            reply = session.handle(f"implement {ticket.ticket_id}")
            assert "closed" in reply.lower() or "done" in reply.lower()
