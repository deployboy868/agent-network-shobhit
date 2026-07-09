"""Tests for per-twin owner briefing memory (cross-session)."""

import os
import tempfile
from unittest.mock import patch

from agent_network import owner_memory
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_INTERN_ID, DEMO_MANAGER_ID


def _temp_db_env():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return patch.dict(os.environ, {"TWIN_MEMORY_DB": tmp.name})


def test_owner_briefings_isolated_per_twin():
    with _temp_db_env():
        owner_memory.reset_owner_memory()
        owner_memory.remember(DEMO_MANAGER_ID, "user", "Don't assign tickets without asking me.")
        owner_memory.remember(DEMO_ASSIGNEE_ID, "user", "Always loop in QA.")
        assert owner_memory.count(DEMO_MANAGER_ID) == 1
        assert owner_memory.count(DEMO_ASSIGNEE_ID) == 1
        owner_memory.clear(DEMO_MANAGER_ID)
        assert owner_memory.count(DEMO_MANAGER_ID) == 0
        assert owner_memory.count(DEMO_ASSIGNEE_ID) == 1
        owner_memory.reset_owner_memory()


def test_should_not_persist_activity_queries():
    assert not owner_memory.should_persist_owner_briefing(
        "what happened while I was away?"
    )
    assert not owner_memory.should_persist_owner_briefing("help")
    assert owner_memory.should_persist_owner_briefing(
        "when the intern asks about sprint planner, walk them through the doc first"
    )


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_briefing_visible_in_intern_session_prompt():
    from agent_network import owner_instruction_memory

    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        owner.handle(
            "when Demo Intern asks about sprint planner, explain the wiki first — "
            "don't create a ticket until they've read it"
        )

        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        prompt = intern.llm_system_prompt()
        assert "sprint planner" in prompt.lower()
        assert "wiki" in prompt.lower()
        assert "Owner rules" in prompt
        owner_instruction_memory.reset_instruction_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_activity_query_not_stored_as_briefing():
    from agent_network import owner_instruction_memory

    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        owner.handle("what happened while I was away?")
        assert owner_instruction_memory.count_active(DEMO_MANAGER_ID) == 0
        owner_instruction_memory.reset_instruction_memory()
