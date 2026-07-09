"""Tests for LLM tool parsing, guards, and execution across all chat tools."""

from __future__ import annotations

import json
from unittest.mock import patch

from agent_network import memory
from agent_network.agent.llm_text_tools import (
    LLM_CHAT_TOOL_NAMES,
    LLM_OWNER_TOOL_NAMES,
    LLM_WORK_TOOL_NAMES,
    parse_text_tool_invocations,
)
from agent_network.agent.llm_tool_exec import collect_invocations, run_tool_batch, summarize_tool_results
from agent_network.agent.llm_tool_guards import guard_and_prepare_tool
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID


class _FakeChoice:
    def __init__(self, content: str = "", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeFn:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _FakeCall:
    def __init__(self, name: str, arguments: dict, call_id: str = "call_1"):
        self.id = call_id
        self.function = _FakeFn(name, json.dumps(arguments))


def test_all_chat_tools_listed():
    assert LLM_WORK_TOOL_NAMES == {
        "jira_list_tickets",
        "jira_get_ticket",
        "twin_create_ticket_for_requester",
        "gitlab_list_merge_requests",
        "gitlab_link_mr_to_ticket",
    }
    assert LLM_OWNER_TOOL_NAMES == {
        "twin_get_stand_in_activity",
        "twin_get_colleague_chat",
        "twin_delegate_ticket",
        "gitlab_create_mr_from_ticket",
    }
    assert LLM_CHAT_TOOL_NAMES == LLM_WORK_TOOL_NAMES | LLM_OWNER_TOOL_NAMES


def test_parse_all_tool_json_shapes():
    cases = [
        (
            "jira_list_tickets",
            '{"name": "jira_list_tickets", "parameters": {}}',
            {},
        ),
        (
            "jira_get_ticket",
            '{"function": "jira_get_ticket", "arguments": {"ticket_id": "JIRA-ABC"}}',
            {"ticket_id": "JIRA-ABC"},
        ),
        (
            "gitlab_list_merge_requests",
            '```json\n{"tool": "gitlab_list_merge_requests", "input": {"state": "opened"}}\n```',
            {"state": "opened"},
        ),
        (
            "gitlab_link_mr_to_ticket",
            '{"name": "gitlab_link_mr_to_ticket", "parameters": {"ticket_id": "JIRA-1", "mr_url": "https://gitlab.example.com/mr/1"}}',
            {"ticket_id": "JIRA-1", "mr_url": "https://gitlab.example.com/mr/1"},
        ),
        (
            "twin_delegate_ticket",
            '{"name": "twin_delegate_ticket", "parameters": {"title": "task", "assignee_employee_id": "Demo Assignee"}}',
            {"title": "task", "assignee_employee_id": "Demo Assignee"},
        ),
    ]
    for expected_name, text, expected_args in cases:
        parsed = parse_text_tool_invocations(text)
        assert len(parsed) == 1, text
        name, args = parsed[0]
        assert name == expected_name
        for key, val in expected_args.items():
            assert args[key] == val


def test_collect_invocations_from_structured_tool_calls():
    choice = _FakeChoice(
        tool_calls=[_FakeCall("jira_list_tickets", {}, "tc1")]
    )
    invocations = collect_invocations(choice)
    assert invocations == [("tc1", "jira_list_tickets", {})]


def test_collect_invocations_ignores_unknown_tools():
    choice = _FakeChoice(
        tool_calls=[_FakeCall("jira_create_ticket", {"title": "x"})]
    )
    assert collect_invocations(choice) == []


def test_colleague_cannot_list_manager_queue_via_llm_guard():
    memory.reset_memory()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    args, blocked = guard_and_prepare_tool(
        session,
        "jira_list_tickets",
        {"assignee_email": session.employee.email},
        "list manager tickets",
    )
    assert blocked is not None
    assert "backlog" in blocked["content"][0]["text"].lower()


def test_gitlab_link_requires_http_url():
    memory.reset_memory()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
    _, blocked = guard_and_prepare_tool(
        session,
        "gitlab_link_mr_to_ticket",
        {"ticket_id": "JIRA-1", "mr_url": "not-a-url"},
        "link mr",
    )
    assert blocked is not None


@patch("agent_network.agent.llm_tool_exec.call_tool")
def test_run_tool_batch_executes_parsed_delegate(mock_call_tool):
    memory.reset_memory()
    session = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
    session.employee.is_absent = True
    mock_call_tool.return_value = {
        "isError": False,
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"success": True, "ticket_id": "JIRA-DEADBEEF", "detail": "ok"}
                ),
            }
        ],
    }
    text = (
        '{"name": "twin_delegate_ticket", "parameters": {'
        '"title": "Sprint planner", "assignee_employee_id": "Demo Assignee"}}'
    )
    invocations = [("parsed_0", "twin_delegate_ticket", parse_text_tool_invocations(text)[0][1])]
    tool_messages, executed = run_tool_batch(
        session, "please delegate sprint planner to assignee", invocations
    )
    assert mock_call_tool.called
    called_name, called_args = mock_call_tool.call_args[0]
    assert called_name == "twin_delegate_ticket"
    assert called_args["reporter_employee_id"] == DEMO_MANAGER_ID
    assert called_args["invoker_employee_id"] == DEMO_MANAGER_ID
    assert called_args["assignee_employee_id"] == "emp-assignee"
    summary = summarize_tool_results(tool_messages)
    assert summary and "JIRA-DEADBEEF" in summary
    assert executed[0][1] == "twin_delegate_ticket"
