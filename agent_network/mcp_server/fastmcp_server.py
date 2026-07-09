"""Official MCP server (FastMCP) — Cursor-compatible stdio transport."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from agent_network.mcp_server.tools_registry import call_tool

mcp = FastMCP("agent-network")


def _run(name: str, arguments: dict | None = None) -> str:
    result = call_tool(name, arguments or {})
    return result["content"][0]["text"]


@mcp.tool()
def agent_network_status() -> str:
    """Show mode (mock/live) and active safety settings."""
    return _run("agent_network_status")


@mcp.tool()
def jira_create_ticket(title: str, description: str, reporter_id: str = "") -> str:
    """Create a Jira ticket with [Agent-Network-TEST] safe prefix."""
    args = {"title": title, "description": description}
    if reporter_id:
        args["reporter_id"] = reporter_id
    return _run("jira_create_ticket", args)


@mcp.tool()
def jira_get_ticket(ticket_id: str) -> str:
    """Read one Jira ticket by key (e.g. LST-46547)."""
    return _run("jira_get_ticket", {"ticket_id": ticket_id})


@mcp.tool()
def jira_list_tickets(assignee_email: str = "") -> str:
    """List demo tickets (read-only). Live mode filters to [Agent-Network-TEST] prefix."""
    args = {"assignee_email": assignee_email} if assignee_email else {}
    return _run("jira_list_tickets", args)


@mcp.tool()
def jira_assign_ticket(ticket_id: str, assignee_employee_id: str) -> str:
    """Assign ticket to an employee. Demo safe mode assigns to JIRA_EMAIL only."""
    return _run(
        "jira_assign_ticket",
        {"ticket_id": ticket_id, "assignee_employee_id": assignee_employee_id},
    )


@mcp.tool()
def jira_mark_ticket_done(ticket_id: str) -> str:
    """Walk Jira workflow to done/closed (safe-prefix tickets only)."""
    return _run("jira_mark_ticket_done", {"ticket_id": ticket_id})


@mcp.tool()
def gitlab_list_merge_requests(state: str = "opened", limit: int = 10) -> str:
    """List merge requests in configured GitLab project (read-only GET)."""
    return _run("gitlab_list_merge_requests", {"state": state, "limit": limit})


@mcp.tool()
def gitlab_link_mr_to_ticket(ticket_id: str, mr_url: str) -> str:
    """Verify MR exists (read-only), add link as Jira comment (no GitLab write)."""
    return _run("gitlab_link_mr_to_ticket", {"ticket_id": ticket_id, "mr_url": mr_url})


@mcp.tool()
def gitlab_create_mr_from_ticket(ticket_id: str) -> str:
    """Owner sub-agent: Jira ticket → Groq artifact → GitLab MR + Jira link."""
    return _run("gitlab_create_mr_from_ticket", {"ticket_id": ticket_id})


@mcp.tool()
def teams_notify_user(email: str, message: str) -> str:
    """Notify user via Teams (mock unless live Teams is configured)."""
    return _run("teams_notify_user", {"email": email, "message": message})


@mcp.tool()
def twin_delegate_ticket(
    reporter_employee_id: str,
    invoker_employee_id: str,
    assignee_employee_id: str,
    title: str,
    description: str = "",
) -> str:
    """Owner-only: create ticket and delegate to another twin via agent bus."""
    return _run(
        "twin_delegate_ticket",
        {
            "reporter_employee_id": reporter_employee_id,
            "invoker_employee_id": invoker_employee_id,
            "assignee_employee_id": assignee_employee_id,
            "title": title,
            "description": description,
        },
    )


@mcp.tool()
def workday_get_employee_manager(employee_id: str) -> str:
    """Look up employee manager (mock unless Workday live)."""
    return _run("workday_get_employee_manager", {"employee_id": employee_id})


if __name__ == "__main__":
    mcp.run(transport="stdio")
