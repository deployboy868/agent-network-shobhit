"""Owner sees colleague chats on demand; colleagues only see their own thread."""

import os
import tempfile
from unittest.mock import patch

from agent_network import memory
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID


def _temp_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return patch.dict(os.environ, {"TWIN_MEMORY_DB": tmp.name})


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_prompt_does_not_load_colleague_transcript_by_default():
    with _temp_db():
        memory.reset_memory()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        intern.handle("I am blocked on the sprint planner wiki section")

        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        prompt = owner.llm_system_prompt()
        assert "sprint planner wiki" not in prompt.lower()
        memory.reset_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_fetches_colleague_transcript_when_asked():
    with _temp_db():
        memory.reset_memory()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        intern.handle("I am blocked on the sprint planner wiki section")

        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        reply = owner.handle("what did the intern say to you?")
        assert "sprint planner wiki" in reply.lower()
        memory.reset_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_colleague_prompt_excludes_other_chats():
    with _temp_db():
        memory.reset_memory()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        intern.handle("secret intern-only blocker on database migration")

        assignee = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id="emp-assignee")
        assignee.employee.is_absent = True
        prompt = assignee.llm_system_prompt()
        assert "database migration" not in prompt.lower()
        memory.reset_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_colleague_cannot_fetch_other_chats():
    with _temp_db():
        memory.reset_memory()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        intern.handle("secret intern-only blocker on database migration")

        assignee = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id="emp-assignee")
        assignee.employee.is_absent = True
        reply = assignee.handle("what did the intern say to you?")
        assert "database migration" not in reply.lower()
        assert "secret intern-only" not in reply.lower()
        assert assignee.fetch_colleague_conversations_for_owner().startswith("Access denied")
        memory.reset_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_llm_colleague_intent_sanitized_for_non_owner():
    from agent_network.agent.message_intent import (
        IntentKind,
        MessageIntent,
        classify_message,
    )

    with _temp_db():
        memory.reset_memory()
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        with patch("agent_network.config.is_llm_enabled", return_value=True):
            with patch(
                "agent_network.agent.message_intent._llm_classify",
                return_value=MessageIntent(
                    IntentKind.QUERY_COLLEAGUE_CHATS, confidence=0.9, source="llm"
                ),
            ):
                intent = classify_message(session, "what did the intern say?")
        assert intent.kind == IntentKind.CHAT
        memory.reset_memory()
    from agent_network.agent.message_intent import IntentKind, classify_message

    with _temp_db():
        memory.reset_memory()
        session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intent = classify_message(session, "what did the intern say to you?")
        assert intent.kind == IntentKind.CHAT
        memory.reset_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_absence_summary_lists_colleagues_without_full_transcript():
    with _temp_db():
        memory.reset_memory()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        intern.handle("need help with handbook appendix")

        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        summary = owner._absence_summary()
        assert "demo intern" in summary.lower() or "intern" in summary.lower()
        assert "handbook appendix" not in summary.lower()
        assert "Tickets created for colleagues" in summary
        memory.reset_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_fetches_only_asked_colleague_chat():
    from agent_network.registry import DEMO_ASSIGNEE_ID

    with _temp_db():
        memory.reset_memory()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        intern.handle("blocked on sprint planner wiki section")

        assignee = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_ASSIGNEE_ID)
        assignee.employee.is_absent = True
        assignee.handle("question about production deploy rollback")

        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        reply = owner.handle("what did the intern say to you?")
        assert "sprint planner wiki" in reply.lower()
        assert "production deploy rollback" not in reply.lower()
        memory.reset_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_asked_which_colleague_without_name():
    with _temp_db():
        memory.reset_memory()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        intern.handle("need help with handbook appendix")

        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        reply = owner.handle("who messaged you while I was away?")
        assert "which colleague" in reply.lower() or "demo intern" in reply.lower()
        assert "handbook appendix" not in reply.lower()
        memory.reset_memory()
