"""Tests for proactive ticket approval flow."""

import json
import os
from unittest.mock import patch

from agent_network.agent.twin_chat import TwinChatSession
from agent_network.mcp import reset_toolset
from agent_network.mcp.mock_tools import MockToolSet
from agent_network.registry import (
    DEMO_INTERN_ID,
    DEMO_MANAGER_ID,
    employee_by_id,
    set_employee_absent,
)
from agent_network.runtime import reset_runtime
from agent_network.standin_policy import get_policy, set_policy
from agent_network import owner_instruction_memory
from agent_network import ticket_approval
from agent_network.models import TwinStandInPolicy


def setup_function():
    ticket_approval.clear_all()
    ticket_approval.reset_ticket_approval_memory()
    owner_instruction_memory.reset_instruction_memory()
    reset_runtime()
    reset_toolset()
    policy = get_policy(DEMO_MANAGER_ID)
    policy.require_ticket_approval = False
    set_policy(DEMO_MANAGER_ID, policy)


def teardown_function():
    ticket_approval.reset_ticket_approval_memory()
    owner_instruction_memory.reset_instruction_memory()
    reset_runtime()
    reset_toolset()


def test_rule_requires_ticket_approval_heuristic():
    assert ticket_approval.rule_requires_ticket_approval(
        "notify and confirm with me before creating tickets"
    )
    assert not ticket_approval.rule_requires_ticket_approval("be friendly to colleagues")


@patch.dict(os.environ, {"MOCK_TOOLS": "true"}, clear=False)
def test_colleague_request_queues_and_owner_approves():
    set_employee_absent(DEMO_MANAGER_ID, True)
    policy = get_policy(DEMO_MANAGER_ID)
    policy.require_ticket_approval = True
    set_policy(DEMO_MANAGER_ID, policy)

    tools = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry._tools", return_value=tools):
        reset_runtime()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        reply = intern.handle("can you make me a ticket for the Sprint Planner?")

    assert "TA-" in reply
    assert "notified" in reply.lower() or "approval" in reply.lower()
    pending = ticket_approval.list_pending(DEMO_MANAGER_ID)
    assert len(pending) == 1
    ref = pending[0]["ref_code"]

    owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    with patch("agent_network.mcp_server.tools_registry._tools", return_value=tools):
        approve_reply = owner.handle(f"approve {ref}")

    assert "created" in approve_reply.lower() or ref.upper() in approve_reply.upper()
    assert ticket_approval.list_pending(DEMO_MANAGER_ID) == []

    intern2 = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    follow_up = intern2.handle("can you make me a ticket for the Sprint Planner?")
    assert "approved" in follow_up.lower() or "JIRA-" in follow_up


@patch.dict(os.environ, {"MOCK_TOOLS": "true"}, clear=False)
def test_owner_reject_pending():
    set_employee_absent(DEMO_MANAGER_ID, True)
    policy = TwinStandInPolicy(require_ticket_approval=True)
    set_policy(DEMO_MANAGER_ID, policy)

    tools = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry._tools", return_value=tools):
        reset_runtime()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.handle("please create a ticket for onboarding handbook")

    ref = ticket_approval.list_pending(DEMO_MANAGER_ID)[0]["ref_code"]
    owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    reply = owner.handle(f"reject {ref}")
    assert "declined" in reply.lower() or "won't" in reply.lower()


def test_owner_hold_and_notify_sets_policy():
    from agent_network.agent.owner_intent import apply_stand_in_flags_from_owner_text

    msg = (
        "do not assign anyone any tickets in my absence. if someone asks to make "
        "a ticket, put them on hold and text me to confirm"
    )
    assert ticket_approval.wants_ticket_hold_and_notify(msg)
    assert apply_stand_in_flags_from_owner_text(DEMO_MANAGER_ID, msg)
    policy = get_policy(DEMO_MANAGER_ID)
    assert policy.can_delegate is False
    assert policy.require_ticket_approval is True


@patch.dict(os.environ, {"MOCK_TOOLS": "true"}, clear=False)
def test_approval_queue_works_when_can_delegate_false():
    """Regression: can_delegate=false must not block notify+queue."""
    set_employee_absent(DEMO_MANAGER_ID, True)
    policy = TwinStandInPolicy(can_delegate=False, require_ticket_approval=True)
    set_policy(DEMO_MANAGER_ID, policy)

    tools = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry._tools", return_value=tools):
        reset_runtime()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        reply = intern.handle(
            "I was given the task to create a sprint planner, can you assign me a ticket?"
        )

    assert "TA-" in reply
    assert ticket_approval.list_pending(DEMO_MANAGER_ID)
    notes = tools.teams.get_notifications(employee_by_id(DEMO_MANAGER_ID).email)
    assert notes


@patch.dict(os.environ, {"MOCK_TOOLS": "true", "LLM_PROVIDER": "none"}, clear=False)
def test_owner_activity_shows_queued_ticket():
    set_employee_absent(DEMO_MANAGER_ID, True)
    policy = TwinStandInPolicy(require_ticket_approval=True)
    set_policy(DEMO_MANAGER_ID, policy)
    tools = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry._tools", return_value=tools):
        reset_runtime()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.handle("can you make me a ticket for Sprint Planner?")

    owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    summary = owner.handle("what happened in my absence")
    assert "TA-" in summary or "approval" in summary.lower()
    assert "Sprint Planner" in summary or "Demo Intern" in summary


def test_myaccess_rule_stored():
    owner_instruction_memory.reset_instruction_memory()
    msg = (
        "tell people wanting generative AI access on MS Copilot Studio to request it on myaccess"
    )
    from agent_network.agent.owner_rule_classifier import classify_owner_rule_ops

    ops = classify_owner_rule_ops(DEMO_MANAGER_ID, msg)
    assert ops[0].get("action") == "add"
    owner_instruction_memory.process_owner_message(DEMO_MANAGER_ID, msg, "")
    rules = owner_instruction_memory.list_active_rules(DEMO_MANAGER_ID)
    assert any("myaccess" in r["rule_text"].lower() for r in rules)


@patch.dict(os.environ, {"MOCK_TOOLS": "true"}, clear=False)
def test_proactive_alert_posted_to_owner_chat():
    import os
    import tempfile
    from unittest.mock import patch as mock_patch

    from agent_network import memory

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    with mock_patch.dict(os.environ, {"TWIN_MEMORY_DB": db_path}):
        memory.reset_memory()
        ticket_approval.reset_ticket_approval_memory()
        set_employee_absent(DEMO_MANAGER_ID, True)
        policy = TwinStandInPolicy(require_ticket_approval=True)
        set_policy(DEMO_MANAGER_ID, policy)
        tools = MockToolSet()
        with patch("agent_network.mcp_server.tools_registry._tools", return_value=tools):
            reset_runtime()
            intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
            intern.handle("can you make me a ticket for Sprint Planner?")

        owner_conv = ticket_approval.owner_session_conversation_id(DEMO_MANAGER_ID)
        turns = memory.recent(owner_conv, limit=20)
        assert any(
            t.get("role") == "assistant" and "Proactive alert" in t.get("content", "")
            for t in turns
        )
        assert any("TA-" in t.get("content", "") for t in turns)
        memory.reset_memory()
        ticket_approval.reset_ticket_approval_memory()


def test_owner_rule_sets_approval_policy():
    owner_instruction_memory.reset_instruction_memory()
    owner_instruction_memory.add_rule(
        DEMO_MANAGER_ID,
        "Notify and confirm with me before creating any ticket for colleagues",
    )
    ticket_approval.sync_ticket_approval_policy(DEMO_MANAGER_ID)
    assert get_policy(DEMO_MANAGER_ID).require_ticket_approval is True
