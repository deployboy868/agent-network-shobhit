"""MCP tool registry smoke tests."""

from unittest.mock import patch

from agent_network.mcp.mock_tools import MockToolSet
from agent_network.mcp_server.tools_registry import call_tool, list_tool_specs


def test_mcp_tools_registered():
    names = {t["name"] for t in list_tool_specs()}
    assert "jira_create_ticket" in names
    assert "gitlab_list_merge_requests" in names
    assert "agent_network_status" in names


def test_mcp_jira_create_mock():
    mock = MockToolSet()
    with patch("agent_network.mcp_server.tools_registry.get_toolset", return_value=mock):
        result = call_tool(
            "jira_create_ticket",
            {"title": "MCP test", "description": "from test"},
        )
    assert not result["isError"]
    assert "ticket_id" in result["content"][0]["text"]
