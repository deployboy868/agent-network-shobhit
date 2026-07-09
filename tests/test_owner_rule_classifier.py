"""Tests for LLM-aware owner rule classification."""

import json
from unittest.mock import MagicMock, patch

from agent_network.agent.owner_rule_classifier import (
    OwnerRuleClassification,
    classify_owner_message,
    derive_policy_from_rules,
)
from agent_network import owner_instruction_memory
from agent_network.registry import DEMO_MANAGER_ID
from agent_network.standin_policy import get_policy, reset_standin_policies


def _mock_llm_response(payload: dict) -> MagicMock:
    msg = MagicMock()
    msg.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


@patch("agent_network.agent.owner_rule_classifier.is_llm_enabled", return_value=True)
@patch("agent_network.agent.llm_router._make_client")
def test_llm_classifies_activity_query_as_not_rule(mock_client, _enabled):
    mock_client.return_value.chat.completions.create.return_value = _mock_llm_response(
        {
            "message_kind": "information_query",
            "reasoning": "Owner is asking for a recap, not setting a rule.",
            "operations": [{"action": "none"}],
            "policy_effects": {},
        }
    )
    result = classify_owner_message(DEMO_MANAGER_ID, "what happened in my absence?")
    assert result.message_kind == "information_query"
    assert result.operations == [{"action": "none"}]


@patch("agent_network.agent.owner_rule_classifier.is_llm_enabled", return_value=True)
@patch("agent_network.agent.llm_router._make_client")
def test_llm_classifies_ticket_notify_rule_with_policy(mock_client, _enabled):
    mock_client.return_value.chat.completions.create.return_value = _mock_llm_response(
        {
            "message_kind": "standing_rule_add",
            "reasoning": "Owner sets ongoing ticket approval workflow.",
            "operations": [
                {
                    "action": "add",
                    "rule_text": (
                        "When a colleague asks for a ticket, put the request on hold, "
                        "notify the owner on Teams, and wait for explicit approval."
                    ),
                    "policy_tags": {
                        "require_ticket_approval": True,
                        "can_delegate": False,
                    },
                }
            ],
            "policy_effects": {
                "require_ticket_approval": True,
                "can_delegate": False,
            },
        }
    )
    msg = (
        "do not assign tickets. if someone asks to make a ticket, "
        "put them on hold and text me to confirm"
    )
    result = classify_owner_message(DEMO_MANAGER_ID, msg)
    assert result.is_rule_mutation
    assert result.policy_effects.get("require_ticket_approval") is True
    op = result.operations[0]
    assert op["action"] == "add"
    assert op["policy_tags"]["require_ticket_approval"] is True


@patch("agent_network.agent.owner_rule_classifier.is_llm_enabled", return_value=True)
@patch("agent_network.agent.llm_router._make_client")
def test_llm_classifies_myaccess_guidance_as_rule(mock_client, _enabled):
    mock_client.return_value.chat.completions.create.return_value = _mock_llm_response(
        {
            "message_kind": "standing_rule_add",
            "reasoning": "Standing guidance for access requests.",
            "operations": [
                {
                    "action": "add",
                    "rule_text": (
                        "Direct colleagues wanting MS Copilot Studio generative AI access "
                        "to submit a request on myaccess."
                    ),
                    "policy_tags": {},
                }
            ],
            "policy_effects": {},
        }
    )
    result = classify_owner_message(
        DEMO_MANAGER_ID,
        "tell people wanting generative AI on Copilot Studio to request on myaccess",
    )
    assert result.is_rule_mutation
    assert "myaccess" in result.operations[0]["rule_text"].lower()


@patch("agent_network.agent.owner_rule_classifier.is_llm_enabled", return_value=True)
@patch("agent_network.agent.owner_rule_classifier._llm_derive_policy")
def test_derive_policy_from_stored_rules(mock_derive, _enabled):
    reset_standin_policies()
    owner_instruction_memory.reset_instruction_memory()
    owner_instruction_memory.add_rule(
        DEMO_MANAGER_ID,
        "Notify owner before creating tickets for colleagues.",
        policy_tags={"require_ticket_approval": True, "can_delegate": False},
    )
    mock_derive.return_value = {
        "require_ticket_approval": True,
        "can_delegate": False,
    }
    flags = derive_policy_from_rules(DEMO_MANAGER_ID)
    assert flags["require_ticket_approval"] is True
    assert flags["can_delegate"] is False
    assert get_policy(DEMO_MANAGER_ID).require_ticket_approval is True
    owner_instruction_memory.reset_instruction_memory()
