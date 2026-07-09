"""
Same assign-and-track demo, orchestrated with LangGraph.

Run:
  PYTHONPATH=. python -m agent_network.demo.assign_and_track_graph
"""

from __future__ import annotations

import logging
import sys

from agent_network.bus import AgentMessageBus
from agent_network.config import is_demo_safe_mode, is_mock_mode, jira_email
from agent_network.graph.assign_flow import run_assign_flow
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
    return {emp.employee_id: DigitalTwinAgent(emp, bus) for emp in SAMPLE_EMPLOYEES}


def main() -> int:
    bus = AgentMessageBus()
    twins = build_twins(bus)

    reporter = twins[DEMO_MANAGER_ID]
    assignee_id = DEMO_ASSIGNEE_ID

    mode = "live Jira" if not is_mock_mode() else "mock tools"
    logger.info("=== LangGraph assign-and-track (%s) ===", mode)
    if not is_mock_mode() and is_demo_safe_mode():
        logger.info(
            "DEMO SAFE MODE: Jira tickets assign to YOU (%s) only.",
            jira_email(),
        )
    logger.info("Reporter twin: %s", employee_display_name(DEMO_MANAGER_ID))
    logger.info("Assignee twin: %s (agent bus only)", employee_display_name(assignee_id))
    logger.info("Graph: delegate → complete → track → END\n")

    state = run_assign_flow(
        reporter,
        twins[assignee_id],
        title="Fix onboarding doc typo",
        description="Update intern handbook section on MCP setup.",
        assignee_employee_id=assignee_id,
    )

    if state.get("error"):
        logger.error("Flow failed: %s", state["error"])
        if state.get("ticket_id"):
            logger.error(
                "Close step may need workflow config. Run:\n"
                "  PYTHONPATH=. python -m agent_network.demo.discover_jira_transitions %s",
                state["ticket_id"],
            )
        return 1

    ticket_id = state.get("ticket_id", "?")
    logger.info("Created ticket %s", ticket_id)
    logger.info("Assignee marked done")
    logger.info("Final ticket status: %s", state.get("final_status", "?"))

    ticket = reporter.tools.jira.get_ticket(ticket_id)
    if ticket and ticket.assignee_id:
        logger.info("Jira assignee account id: %s", ticket.assignee_id)

    logger.info("=== LangGraph demo complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
