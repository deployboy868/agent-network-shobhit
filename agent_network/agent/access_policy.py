"""
Stand-in judgment: what the absent employee would reasonably do.

This is NOT a generic permission system. The twin acts *as* the owner.
These rules approximate how a real manager/engineer would behave when a
colleague asks for help — e.g. help with their blocker, not dump an
unrelated private backlog.

With an LLM, the same boundaries move into the system prompt; tools stay
bound to the owner's identity and skills.
"""

from __future__ import annotations

from typing import Any, Optional

from agent_network.models import Skill, TaskStatus
from agent_network.registry import employee_by_id, employee_display_name, employee_has_skill


def requester_is_twin_owner(requester_employee_id: Optional[str], twin_employee_id: str) -> bool:
    return bool(requester_employee_id and requester_employee_id == twin_employee_id)


def owner_is_direct_command(
    requester_employee_id: Optional[str], twin_employee_id: str
) -> bool:
    """The twin owner speaking to their own twin — full authority over stand-in policy."""
    return requester_is_twin_owner(requester_employee_id, twin_employee_id)


def deny_list_twin_queue(
    requester_employee_id: Optional[str],
    twin_employee_id: str,
    scope: str,
) -> Optional[str]:
    """
    Standing in for the owner: they wouldn't paste their entire backlog into chat.
    Help the colleague with *their* work instead.
    """
    if scope != "twin":
        return None
    if requester_is_twin_owner(requester_employee_id, twin_employee_id):
        return None
    owner_name = employee_display_name(twin_employee_id)
    return (
        f"While standing in for {owner_name}, I wouldn't walk you through their full backlog — "
        "that's not how they'd normally help a colleague.\n\n"
        "Tell me what you're blocked on, or try:\n"
        "  • list my tickets — pull up your work\n"
        "  • status TICKET-ID — on a ticket you're on\n"
        "  • create a ticket for <task> — get work on your board"
    )


def deny_delegate_from_colleague(
    requester_employee_id: Optional[str],
    twin_employee_id: str,
) -> Optional[str]:
    """Only the twin owner may route work to other teammates."""
    if requester_is_twin_owner(requester_employee_id, twin_employee_id):
        return None
    owner_name = employee_display_name(twin_employee_id)
    return (
        f"Only {owner_name} can tell me to delegate work to someone else — "
        "that's their call, not yours.\n\n"
        "If you need something tracked on **your** board, ask me to create a ticket for you."
    )


def can_view_ticket(
    requester_employee_id: Optional[str],
    twin_employee_id: str,
    ticket: dict[str, Any],
) -> bool:
    """Owner can see anything; colleagues only tickets assigned to them."""
    if not requester_employee_id:
        return requester_is_twin_owner(None, twin_employee_id)
    if requester_is_twin_owner(requester_employee_id, twin_employee_id):
        return True

    assignee = ticket.get("assignee_id")
    if assignee and assignee == requester_employee_id:
        return True

    requester = employee_by_id(requester_employee_id)
    if requester and ticket.get("assignee_email") == requester.email:
        return True

    return False


def deny_implement_mr(
    requester_employee_id: Optional[str],
    twin_employee_id: str,
) -> Optional[str]:
    """MR-from-ticket: own twin only, and twin must have GitLab skill."""
    if not requester_is_twin_owner(requester_employee_id, twin_employee_id):
        owner_name = employee_display_name(twin_employee_id)
        return (
            f"Only {owner_name} can ask their own twin to open a merge request from a ticket."
        )
    if not employee_has_skill(twin_employee_id, Skill.GITLAB):
        owner_name = employee_display_name(twin_employee_id)
        return (
            f"{owner_name}'s twin doesn't have GitLab access — "
            "MR generation isn't available for this role."
        )
    return None


def deny_implement_mr_closed_ticket(status: TaskStatus) -> Optional[str]:
    """MR-from-ticket only for tickets that are still open or in progress."""
    if status == TaskStatus.DONE:
        return (
            "That ticket is already closed or done — I won't open a new merge request "
            "for it. Reopen the ticket in Jira first if you still need implementation."
        )
    return None


def deny_view_ticket(
    requester_employee_id: Optional[str],
    twin_employee_id: str,
    ticket_id: str,
) -> Optional[str]:
    if requester_is_twin_owner(requester_employee_id, twin_employee_id):
        return None
    owner_name = employee_display_name(twin_employee_id)
    return (
        f"{ticket_id} isn't assigned to you — standing in for {owner_name}, "
        "I'd only look up tickets on your plate. "
        "Try list my tickets, or share a ticket ID that's yours."
    )
