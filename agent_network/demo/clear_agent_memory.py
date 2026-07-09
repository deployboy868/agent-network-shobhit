"""
Wipe persisted twin state for fresh testing.

Clears: chat memory, owner rules, owner briefings (legacy), audit log, stand-in policy file,
mock tool notifications, in-process demo roster absence flags.

Run:
  PYTHONPATH=. python -m agent_network.demo.clear_agent_memory
  ./scripts/fresh-testing.sh
"""

from __future__ import annotations

from agent_network import memory, owner_instruction_memory, owner_memory
from agent_network.audit import clear_audit_log
from agent_network.mcp import reset_toolset
from agent_network.registry import reset_demo_roster_state
from agent_network.runtime import reset_runtime
from agent_network.standin_policy import reset_standin_policies
from agent_network.ticket_approval import clear_all as clear_ticket_approvals
from agent_network.ticket_approval import reset_ticket_approval_memory


def clear_all_agent_memory() -> dict[str, int]:
    """Backward-compatible alias."""
    return reset_for_fresh_testing()


def reset_for_fresh_testing() -> dict[str, int]:
    chat_rows = memory.clear_all()
    rule_rows = owner_instruction_memory.clear_all()
    briefing_rows = owner_memory.clear_all()
    audit_rows = clear_audit_log()
    approval_rows = clear_ticket_approvals()
    memory.reset_memory()
    owner_instruction_memory.reset_instruction_memory()
    owner_memory.reset_owner_memory()
    reset_ticket_approval_memory()
    reset_standin_policies()
    reset_demo_roster_state()
    reset_toolset()
    reset_runtime()
    try:
        from agent_network.mcp.mock_tools import MockTeams

        MockTeams.clear_notifications()
    except Exception:
        pass
    return {
        "chat_turns": chat_rows,
        "owner_rules": rule_rows,
        "owner_briefings": briefing_rows,
        "audit_entries": audit_rows,
        "ticket_approvals": approval_rows,
    }


def main() -> None:
    counts = reset_for_fresh_testing()
    print(
        "Fresh testing reset:",
        f"{counts['chat_turns']} chat turn(s),",
        f"{counts.get('owner_rules', 0)} owner rule(s),",
        f"{counts['owner_briefings']} owner briefing(s),",
        f"{counts['audit_entries']} audit entry(ies);",
        "stand-in policies + demo roster + mock state reset.",
    )


if __name__ == "__main__":
    main()
