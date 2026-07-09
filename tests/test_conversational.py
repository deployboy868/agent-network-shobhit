"""Tests for human conversational replies."""

import os
from unittest.mock import patch

from agent_network.agent.conversational import (
    conversational_fallback,
    is_explicit_help_request,
)
from agent_network.agent.message_intent import IntentKind, _intent_from_json
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.mcp import reset_toolset
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID
from agent_network.runtime import reset_runtime


def test_need_help_is_not_explicit_help():
    assert not is_explicit_help_request("hi I need help")
    assert is_explicit_help_request("help")


def test_llm_help_intent_remapped_to_chat():
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    intent = _intent_from_json(
        {"intent": "help", "confidence": 0.9}, "hi I need help", session
    )
    assert intent.kind == IntentKind.CHAT


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_vague_help_gets_human_reply_not_command_dump():
    reset_toolset()
    reset_runtime()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    session.employee.is_absent = True
    reply = session.handle("hi I need help")
    lower = reply.lower()
    assert "commands:" not in lower
    assert "list my tickets" not in lower or "what" in lower
    assert "stand-in note" not in lower
    assert any(w in lower for w in ("hey", "help", "blocker", "going", "what"))


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_explicit_help_is_human_not_command_dump():
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    session.employee.is_absent = True
    reply = session.handle("help")
    lower = reply.lower()
    assert "commands:" not in lower
    assert "stand-in note" not in lower
    assert any(w in lower for w in ("ticket", "help", "covering", "stuck", "what"))
