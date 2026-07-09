"""
List and summarize tickets (read-only) — manager 'fetch and review progress' demo.

Safe: does NOT create or modify Jira issues.

Run:
  PYTHONPATH=. python -m agent_network.demo.review_tasks
"""

from __future__ import annotations

import logging
import sys

from agent_network.bus import AgentMessageBus
from agent_network.config import is_mock_mode
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_MANAGER_ID, SAMPLE_EMPLOYEES
from agent_network.twin import DigitalTwinAgent

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    bus = AgentMessageBus()
    twins = {e.employee_id: DigitalTwinAgent(e, bus) for e in SAMPLE_EMPLOYEES}
    agent = twins[DEMO_MANAGER_ID]

    mode = "mock" if is_mock_mode() else "live Jira (read-only)"
    logger.info("=== Task review (%s) ===\n", mode)

    try:
        report = agent.review_tasks()
    except (RuntimeError, OSError) as e:
        logger.error("Could not reach Jira: %s", e)
        logger.error("Check VPN/network, or use AGENT_NETWORK_MODE=mock for offline demo.")
        return 1

    if not report.items and is_mock_mode():
        logger.info("Mock mode starts fresh each run — creating one sample ticket to review...\n")
        seeded = agent.create_and_delegate_ticket(
            title="[Agent-Network-TEST] Sample for review",
            description="Auto-created so review_tasks has something to list.",
            assignee_employee_id=DEMO_ASSIGNEE_ID,
        )
        if seeded.success:
            twins[DEMO_ASSIGNEE_ID].mark_ticket_done(seeded.data["ticket_id"])
        report = agent.review_tasks()

    logger.info("%s\n", report.summary_text())

    if not report.items:
        logger.info("No tickets to show.")
        if not is_mock_mode():
            logger.info("Tip: check [Agent-Network-TEST] tickets exist in Jira, or run assign_and_track.")
        return 0

    for item in report.items:
        logger.info(
            "  %s | %s | %s",
            item.ticket_id,
            item.status_label,
            item.title[:60],
        )

    logger.info("\n=== Review complete (no issues were modified) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
