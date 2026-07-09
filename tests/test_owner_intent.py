"""Tests for owner natural-language stand-in directives."""

from agent_network.agent.owner_intent import (
    apply_owner_instruction,
    is_delegate_activity_query,
    is_owner_activity_query,
    is_owner_instruction_message,
    wants_no_delegation,
)
from agent_network.registry import DEMO_MANAGER_ID
from agent_network.standin_policy import get_policy, reset_standin_policies


def test_instruction_cues_detected():
    msg = (
        "okay. make sure you don't assign anyone tickets when I'm away. "
        "ill assign tickets only by myself. keep this in mind"
    )
    lower = msg.lower()
    assert is_owner_instruction_message(lower)
    assert wants_no_delegation(lower)
    assert not is_owner_activity_query(lower)


def test_activity_cues_detected():
    assert is_owner_activity_query("anything happened when i was away?")
    assert is_delegate_activity_query("and did you assign anyone tickets?")


def test_apply_owner_instruction_disables_delegation():
    reset_standin_policies()
    text = "make sure you don't assign anyone tickets when I'm away. keep this in mind"
    reply = apply_owner_instruction(DEMO_MANAGER_ID, text, text.lower())
    policy = get_policy(DEMO_MANAGER_ID)
    assert policy.can_delegate is False
    assert "don't assign" in policy.instructions.lower()
    assert "you can always direct me" in reply.lower()


def test_not_to_assign_phrasing_disables_delegation():
    reset_standin_policies()
    from agent_network.agent.owner_intent import apply_stand_in_flags_from_owner_text

    msg = "do not assign any tickets in my absence"
    assert wants_no_delegation(msg.lower())
    assert is_owner_instruction_message(msg.lower())
    assert apply_stand_in_flags_from_owner_text(DEMO_MANAGER_ID, msg)
    assert get_policy(DEMO_MANAGER_ID).can_delegate is False
