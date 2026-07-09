"""Tests for ticket title extraction from natural language."""

from agent_network.agent.ticket_title import (
    extract_ticket_title_from_request,
    normalize_ticket_title,
)


def test_assigned_task_to_create_sprint_planner_not_same():
    msg = (
        "I have been assigned the task to create a sprint planner by my manager, "
        "can you assign me a ticket for the same??"
    )
    assert extract_ticket_title_from_request(msg) == "Sprint Planner"


def test_ticket_for_the_same_falls_back_to_task_description():
    msg = "can you make me a ticket for the same? I was assigned the task to create a sprint planner"
    assert extract_ticket_title_from_request(msg) == "Sprint Planner"


def test_rejects_pronoun_only_title():
    assert normalize_ticket_title("same", "ticket for the same") == ""
    assert normalize_ticket_title("the same", "") == ""


def test_normalize_reextracts_from_message():
    msg = (
        "assigned the task to create a sprint planner, "
        "can you assign me a ticket for the same"
    )
    assert normalize_ticket_title("same", msg) == "Sprint Planner"


def test_sprint_planner_phrase():
    assert extract_ticket_title_from_request("please create a ticket for sprint planner") == "Sprint Planner"
