"""Tests for dynamic owner instruction rules (persistent, cross-session)."""

import os
import tempfile
from unittest.mock import patch

from agent_network import owner_instruction_memory
from agent_network.agent.owner_rule_classifier import classify_owner_rule_ops
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID


def _temp_db_env():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return patch.dict(os.environ, {"TWIN_MEMORY_DB": tmp.name})


def test_add_and_list_rules():
    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        rid = owner_instruction_memory.add_rule(
            DEMO_MANAGER_ID,
            "When intern asks about sprint planner, explain the wiki first.",
        )
        assert rid is not None
        rules = owner_instruction_memory.list_active_rules(DEMO_MANAGER_ID)
        assert len(rules) == 1
        assert "sprint planner" in rules[0]["rule_text"].lower()
        owner_instruction_memory.reset_instruction_memory()


def test_heuristic_extracts_instruction_from_owner_message():
    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        msg = (
            "when Demo Intern asks about sprint planner, explain the wiki first — "
            "don't create a ticket until they've read it"
        )
        ops = classify_owner_rule_ops(DEMO_MANAGER_ID, msg)
        assert any(op.get("action") == "add" for op in ops)
        owner_instruction_memory.reset_instruction_memory()


def test_activity_query_does_not_create_rule():
    ops = classify_owner_rule_ops(DEMO_MANAGER_ID, "what happened while I was away?")
    assert ops == [{"action": "none"}]


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_rule_visible_in_intern_session_prompt():
    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        owner.handle(
            "when Demo Intern asks about sprint planner, explain the wiki first — "
            "don't create a ticket until they've read it"
        )

        assert owner_instruction_memory.count_active(DEMO_MANAGER_ID) >= 1
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        prompt = intern.llm_system_prompt()
        assert "sprint planner" in prompt.lower()
        assert "wiki" in prompt.lower()
        assert "Owner rules" in prompt
        owner_instruction_memory.reset_instruction_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_activity_query_not_stored_as_rule():
    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        owner.handle("what happened while I was away?")
        assert owner_instruction_memory.count_active(DEMO_MANAGER_ID) == 0
        owner_instruction_memory.reset_instruction_memory()


def test_revoke_rule_by_topic():
    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        owner_instruction_memory.add_rule(
            DEMO_MANAGER_ID,
            "When intern asks about sprint planner, walk them through the wiki.",
        )
        ops = classify_owner_rule_ops(
            DEMO_MANAGER_ID,
            "forget the sprint planner rule — I will handle that myself",
        )
        assert any(op.get("action") == "revoke" for op in ops)
        owner_instruction_memory.process_owner_message(
            DEMO_MANAGER_ID,
            "forget the sprint planner rule — I will handle that myself",
        )
        assert owner_instruction_memory.count_active(DEMO_MANAGER_ID) == 0
        owner_instruction_memory.reset_instruction_memory()


def test_update_rule_replaces_similar():
    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        rid = owner_instruction_memory.add_rule(
            DEMO_MANAGER_ID,
            "Tell intern to read the wiki for sprint planner.",
        )
        result = owner_instruction_memory.process_owner_message(
            DEMO_MANAGER_ID,
            "change that to: for sprint planner, send them the Confluence link first",
        )
        assert result["applied"]
        rules = owner_instruction_memory.list_active_rules(DEMO_MANAGER_ID)
        assert len(rules) == 1
        assert "confluence" in rules[0]["rule_text"].lower()
        assert rules[0]["id"] == rid
        owner_instruction_memory.reset_instruction_memory()


def test_colleague_cannot_set_owner_rules():
    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.handle("when someone asks about deploy, tell them no")
        assert owner_instruction_memory.count_active(DEMO_MANAGER_ID) == 0
        owner_instruction_memory.reset_instruction_memory()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_colleague_copilot_question_uses_owner_rule_not_generic_loop():
    with _temp_db_env():
        owner_instruction_memory.reset_instruction_memory()
        owner_instruction_memory.add_rule(
            DEMO_MANAGER_ID,
            "tell people wanting Copilot Studio generative AI access to request on myaccess",
        )
        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        reply = intern.handle(
            "Can you tell me where to get access of generative AI features on copilot studio?"
        )
        lower = reply.lower()
        assert "what are you working on" not in lower
        assert "myaccess" in lower
        owner_instruction_memory.reset_instruction_memory()
