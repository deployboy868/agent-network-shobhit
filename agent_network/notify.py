"""Notify twin owner during absence (Teams mock or live)."""

from __future__ import annotations

from agent_network.config import is_mock_mode
from agent_network.registry import employee_by_id
from agent_network.standin_policy import get_policy


def notify_twin_owner(twin_employee_id: str, message: str) -> str | None:
    """
    Send Teams notification to the twin owner if policy allows.
    Returns status line for chat, or None if skipped.
    """
    from agent_network.absence import is_effectively_absent
    from agent_network.mcp_server.tools_registry import call_tool

    emp = employee_by_id(twin_employee_id)
    if not emp or not is_effectively_absent(twin_employee_id):
        return None

    policy = get_policy(twin_employee_id)
    if not policy.notify_on_delegate:
        return None

    result = call_tool(
        "teams_notify_user",
        {
            "email": emp.email,
            "message": message,
            "purpose": "owner_stand_in",
        },
    )
    if result.get("isError"):
        return f"(Teams notify failed: {result['content'][0]['text']})"

    channel = "Teams (mock)" if is_mock_mode() else "Teams"
    return f"Notified {emp.name} on {channel}: {message[:120]}"


def notify_owner_ticket_approval_request(
    twin_employee_id: str,
    message: str,
    *,
    ref_code: str = "",
) -> str | None:
    """
    Proactively ping the twin owner when a colleague's ticket request needs approval.
    Works while the owner is absent; does not require notify_on_delegate.
    """
    from agent_network.absence import is_effectively_absent
    from agent_network.mcp_server.tools_registry import call_tool

    emp = employee_by_id(twin_employee_id)
    if not emp or not is_effectively_absent(twin_employee_id):
        return None

    result = call_tool(
        "teams_notify_user",
        {
            "email": emp.email,
            "message": message,
            "purpose": "ticket_approval_request",
            "ref_code": ref_code,
        },
    )
    if result.get("isError"):
        return f"(Teams notify failed: {result['content'][0]['text']})"

    channel = "Teams (mock)" if is_mock_mode() else "Teams"
    return f"Notified {emp.name} on {channel} about approval {ref_code or 'request'}."
