"""Tests for LLM tool guardrails."""

from __future__ import annotations

import json
from unittest.mock import patch

from agent_network.agent.llm_tool_guards import (
    guard_and_prepare_tool,
    known_ticket_ids,
    resolve_ticket_id,
    user_wants_delegate,
)
from agent_network.agent.twin_chat import TwinChatSession
from agent_network import memory
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID


def test_user_wants_delegate_requires_explicit_intent():
    assert user_wants_delegate("delegate handbook fix to assignee")
    assert not user_wants_delegate("I need help")
    assert not user_wants_delegate("hi")


def test_delegate_blocked_for_vague_help():
    memory.reset_memory()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    session.employee.is_absent = True
    _, blocked = guard_and_prepare_tool(
        session,
        "twin_delegate_ticket",
        {
            "reporter_employee_id": "wrong",
            "assignee_employee_id": "emp-assignee",
            "title": "handbook fix",
        },
        "I need help",
    )
    assert blocked is not None
    assert "only" in blocked["content"][0]["text"].lower()


def test_delegate_blocked_for_colleague_even_when_explicit():
    memory.reset_memory()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    session.employee.is_absent = True
    _, blocked = guard_and_prepare_tool(
        session,
        "twin_delegate_ticket",
        {"title": "handbook fix"},
        "please delegate handbook fix to assignee",
    )
    assert blocked is not None
    assert "only" in blocked["content"][0]["text"].lower()


def test_resolve_this_ticket_from_memory():
    memory.reset_memory()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    memory.clear(session.conversation_id)
    memory.remember(
        session.conversation_id,
        "assistant",
        "Ticket delegated: JIRA-0946E8FC",
        DEMO_MANAGER_ID,
    )
    assert known_ticket_ids(session) == ["JIRA-0946E8FC"]
    resolved = resolve_ticket_id(
        session, "JIRA-8A4504B1", "can you show me the status of this ticket"
    )
    assert resolved == "JIRA-0946E8FC"


def test_delegate_allowed_when_owner_explicit():
    memory.reset_memory()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    session.employee.is_absent = True
    args, blocked = guard_and_prepare_tool(
        session,
        "twin_delegate_ticket",
        {"title": "handbook fix"},
        "please delegate handbook fix to assignee",
    )
    assert blocked is None
    assert args["reporter_employee_id"] == DEMO_MANAGER_ID
    assert args["invoker_employee_id"] == DEMO_MANAGER_ID
    assert args["assignee_employee_id"] == "emp-assignee"
