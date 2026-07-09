"""
Demo: one agent creates a ticket, assigns another owner's twin, and tracks completion.

Run:
  python -m agent_network.demo.assign_and_track
"""

from __future__ import annotations

import logging
import sys

from agent_network.bus import AgentMessageBus
from agent_network.config import is_demo_safe_mode, is_mock_mode, jira_email
from agent_network.registry import (
    DEMO_ASSIGNEE_ID,
    DEMO_MANAGER_ID,
    SAMPLE_EMPLOYEES,
    employee_display_name,
)
from agent_network.twin import DigitalTwinAgent

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def build_twins(bus: AgentMessageBus) -> dict[str, DigitalTwinAgent]:
    twins: dict[str, DigitalTwinAgent] = {}
    for emp in SAMPLE_EMPLOYEES:
        twins[emp.employee_id] = DigitalTwinAgent(emp, bus)
    return twins


def main() -> int:
    bus = AgentMessageBus()
    twins = build_twins(bus)

    reporter = twins[DEMO_MANAGER_ID]
    assignee_id = DEMO_ASSIGNEE_ID

    mode = "live Jira" if not is_mock_mode() else "mock tools"
    logger.info("=== Agent Social Network Demo (%s) ===", mode)
    if not is_mock_mode() and is_demo_safe_mode():
        logger.info(
            "DEMO SAFE MODE: Jira tickets assign to YOU (%s) only — "
            "no real colleagues notified.",
            jira_email(),
        )
    logger.info("Reporter twin: %s", employee_display_name(DEMO_MANAGER_ID))
    logger.info("Assignee twin: %s (agent bus only)", employee_display_name(assignee_id))

    result = reporter.create_and_delegate_ticket(
        title="Fix onboarding doc typo",
        description="Update intern handbook section on MCP setup.",
        assignee_employee_id=assignee_id,
    )
    if not result.success:
        logger.error("Delegation failed: %s", result.detail)
        return 1

    ticket_id = result.data["ticket_id"]
    logger.info("Created ticket %s", ticket_id)

    assignee = twins[assignee_id]
    done_result = assignee.mark_ticket_done(ticket_id)
    logger.info("Assignee marked done: %s", done_result.detail)
    if not done_result.success:
        logger.error(
            "Close step failed. Run:\n"
            "  PYTHONPATH=. python -m agent_network.demo.discover_jira_transitions %s",
            ticket_id,
        )
        return 1

    final_status = reporter.follow_up_until_done(ticket_id, assignee_id)
    ticket = reporter.tools.jira.get_ticket(ticket_id)
    logger.info("Final ticket status: %s", final_status.value)
    if ticket and ticket.assignee_id:
        logger.info("Jira assignee account id: %s", ticket.assignee_id)

    logger.info("=== Demo complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
