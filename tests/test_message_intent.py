"""Tests for semantic message intent classification."""

from agent_network.agent.message_intent import IntentKind, _heuristic_classify
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.registry import DEMO_MANAGER_ID


def test_heuristic_instruction_not_work_tools():
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    msg = (
        "okay. make sure you don't assign anyone tickets when I'm away. "
        "ill assign tickets only by myself. keep this in mind"
    )
    intent = _heuristic_classify(session, msg)
    assert intent.kind == IntentKind.REMEMBER_INSTRUCTION
    assert intent.disable_delegation is True


def test_heuristic_activity_query():
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    intent = _heuristic_classify(session, "anything happened when I was away?")
    assert intent.kind == IntentKind.QUERY_ACTIVITY


def test_heuristic_delegate_query():
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    intent = _heuristic_classify(session, "and did you assign anyone tickets?")
    assert intent.kind == IntentKind.QUERY_DELEGATIONS


def test_heuristic_colleague_chat_query():
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    intent = _heuristic_classify(session, "what did the intern say to you?")
    assert intent.kind == IntentKind.QUERY_COLLEAGUE_CHATS


def test_heuristic_list_tickets_is_work():
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    intent = _heuristic_classify(session, "what tickets do I have open right now?")
    assert intent.kind == IntentKind.WORK_TOOLS
