"""
Test Jira credentials before running the full agent demo.

Run (after filling .env):
  AGENT_NETWORK_MODE=live PYTHONPATH=. python -m agent_network.demo.verify_jira
"""

from __future__ import annotations

import logging
import sys

from agent_network.config import is_mock_mode
from agent_network.mcp import get_toolset, reset_toolset

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    if is_mock_mode():
        logger.error(
            "Set AGENT_NETWORK_MODE=live in .env and add Jira variables. See .env.example."
        )
        return 1

    reset_toolset()
    jira = get_toolset().jira

    logger.info("Creating a test issue in Jira...")
    try:
        ticket = jira.create_ticket(
            title="Connection test — safe to delete",
            description="Created by verify_jira.py. You can close or delete this issue.",
            reporter_id="verify-script",
        )
    except RuntimeError as e:
        if "issuetype" in str(e).lower():
            logger.error("%s", e)
            logger.error(
                "Invalid JIRA_ISSUE_TYPE. Run:\n"
                "  PYTHONPATH=. python -m agent_network.demo.discover_jira_issue_types"
            )
        else:
            logger.error("%s", e)
        return 1
    logger.info("Created: %s", ticket.ticket_id)

    fetched = jira.get_ticket(ticket.ticket_id)
    if fetched:
        logger.info("Read back: %s — status %s", fetched.ticket_id, fetched.status.value)

    logger.info("SUCCESS — Jira API is working. Issue key: %s", ticket.ticket_id)
    logger.info("Next: run assign_and_track with live mode (creates another ticket).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
