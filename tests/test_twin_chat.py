"""Tests for human-to-twin chat."""

import os
from unittest.mock import patch

from agent_network.agent.twin_chat import TwinChatSession
from agent_network.mcp import get_toolset, reset_toolset
from agent_network.mcp.mock_tools import MockTeams, MockToolSet
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_INTERN_ID, DEMO_MANAGER_ID
from agent_network.runtime import reset_runtime


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_twin_chat_list_and_delegate():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            get_toolset()
            session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
            assert "stand-in" in session.greeting().lower() or "away" in session.greeting().lower()

            list_reply = session.handle("list my tickets")
            assert "ticket" in list_reply.lower()

            blocked = session.handle("delegate onboarding handbook fix to assignee")
            assert "only" in blocked.lower() or "owner" in blocked.lower() or "delegate work" in blocked.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_can_delegate_while_absent():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
            session.employee.is_absent = True
            delegate_reply = session.handle("delegate onboarding handbook fix to assignee")
            assert "delegated" in delegate_reply.lower() or "done" in delegate_reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_twin_chat_get_status_by_mock_ticket_id():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        ticket_id = next(iter(mock.jira._tickets.keys()))
        reply = session.handle(f"status {ticket_id}")
        assert ticket_id in reply
        assert "Title:" in reply
        assert "Status:" in reply
        assert "Comments:" in reply


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_list_my_tickets_uses_requester():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        reply = session.handle("list my tickets")
        assert "Intern blocker" in reply or "1 " in reply
        assert "Demo Intern" in reply or "ticket" in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_intern_cannot_list_manager_queue():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        reply = session.handle("list your tickets")
        assert "backlog" in reply.lower() or "wouldn't" in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_intern_can_view_own_ticket_only():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern_ticket = next(
            tid
            for tid, t in mock.jira._tickets.items()
            if t.assignee_id == DEMO_INTERN_ID
        )
        assignee_ticket = next(
            tid
            for tid, t in mock.jira._tickets.items()
            if t.assignee_id == DEMO_ASSIGNEE_ID
        )
        ok = session.handle(f"status {intern_ticket}")
        assert "Title:" in ok
        blocked = session.handle(f"status {assignee_ticket}")
        assert "assigned to you" in blocked.lower() or "isn't assigned" in blocked.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_intern_cannot_view_ticket_they_only_reported():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        ticket = mock.jira.create_ticket(
            "[Agent-Network-TEST] Intern reported only",
            "Reporter is intern, assignee is someone else.",
            DEMO_INTERN_ID,
        )
        mock.jira.assign_ticket(ticket.ticket_id, DEMO_ASSIGNEE_ID)
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        reply = session.handle(f"status {ticket.ticket_id}")
        assert "assigned to you" in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_can_delegate_when_present():
    from agent_network.registry import set_employee_absent
    from agent_network.standin_policy import get_policy, reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    set_employee_absent(DEMO_MANAGER_ID, False)
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
            get_policy(DEMO_MANAGER_ID).can_delegate = False
            reply = session.handle(
                "assign the demo assignee a ticket about on call summary generator. do it"
            )
            assert "delegated" in reply.lower() or "done" in reply.lower() or "JIRA-" in reply


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_can_delegate_despite_stand_in_policy():
    from agent_network.standin_policy import get_policy, reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
            session.employee.is_absent = True
            session.handle(
                "make sure you don't assign anyone tickets when I'm away. keep this in mind"
            )
            assert get_policy(DEMO_MANAGER_ID).can_delegate is False
            reply = session.handle("delegate onboarding handbook fix to assignee")
            assert "delegated" in reply.lower() or "done" in reply.lower() or "JIRA-" in reply


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_go_absent_and_summary():
    from agent_network.standin_policy import reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        reply = session.handle("go absent")
        assert "absent" in reply.lower()
        assert session.employee.is_absent

        back = session.handle("go present")
        assert "present" in back.lower()
        assert not session.employee.is_absent


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_gitlab_list_merge_requests():
    reset_toolset()
    reset_runtime()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        reply = session.handle("list merge requests")
        assert "merge request" in reply.lower()
        assert "!42" in reply or "twin stand-in" in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_sets_instructions():
    from agent_network.standin_policy import get_policy, reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        reply = session.handle("instructions: only delegate P0 issues to assignee")
        assert "got it" in reply.lower() or "follow" in reply.lower()
        assert "P0" in get_policy(DEMO_MANAGER_ID).instructions


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_schedules_absence_window_makes_twin_absent():
    from agent_network.absence import is_effectively_absent
    from agent_network.registry import set_employee_absent
    from agent_network.standin_policy import reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    set_employee_absent(DEMO_MANAGER_ID, False)
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        # A window spanning today (UTC) in ISO date form.
        reply = session.handle("absent from 2020-01-01 to 2099-12-31")
        assert "stand in" in reply.lower() or "scheduled" in reply.lower()
        assert is_effectively_absent(DEMO_MANAGER_ID)


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_natural_language_instruction_no_delegate():
    from agent_network.standin_policy import get_policy, reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        msg = (
            "okay. make sure you don't assign anyone tickets when I'm away. "
            "ill assign tickets only by myself. keep this in mind"
        )
        reply = session.handle(msg)
        policy = get_policy(DEMO_MANAGER_ID)
        assert "got it" in reply.lower()
        assert policy.can_delegate is False
        assert "assign" in policy.instructions.lower()
        assert "jira ticket list is empty" not in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_activity_while_away_uses_audit_not_llm():
    from agent_network.audit import log_twin_action
    from agent_network.standin_policy import reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        log_twin_action(
            twin_employee_id=DEMO_MANAGER_ID,
            action="owner_set_instructions",
            detail="test instruction",
        )
        reply = session.handle("anything happened when I was away?")
        assert "owner_set_instructions" in reply or "test instruction" in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_owner_delegate_activity_query():
    from agent_network.audit import log_twin_action
    from agent_network.standin_policy import reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        log_twin_action(
            twin_employee_id=DEMO_MANAGER_ID,
            action="twin_delegate_ticket",
            detail="Ticket created and assignment sent to peer agent",
            data={"ticket_id": "JIRA-TEST01", "assignee_employee_id": DEMO_ASSIGNEE_ID},
        )
        reply = session.handle("and did you assign anyone tickets?")
        assert "yes" in reply.lower()
        assert "delegated" in reply.lower()
        assert "JIRA-TEST01" in reply


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"})
def test_delegate_notifies_owner_on_teams_mock():
    from agent_network.standin_policy import reset_standin_policies

    reset_toolset()
    reset_runtime()
    reset_standin_policies()
    MockTeams.clear_notifications()
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        with patch("agent_network.mcp.get_toolset", return_value=mock):
            session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
            session.employee.is_absent = True
            reply = session.handle("delegate handbook fix to assignee")
            assert "delegated" in reply.lower() or "done" in reply.lower()
            notes = MockTeams.get_notifications(session.employee.email)
            assert len(notes) >= 1
