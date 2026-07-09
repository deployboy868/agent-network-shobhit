"""
List workflow buttons (transitions) available for a Jira issue.

Use an open test ticket key, e.g. LST-45053 from verify_jira or assign_and_track.

Run:
  PYTHONPATH=. python -m agent_network.demo.discover_jira_transitions LST-45053
"""

from __future__ import annotations

import logging
import sys

from agent_network.config import is_mock_mode
from agent_network.mcp import get_toolset, reset_toolset

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    if len(sys.argv) < 2:
        logger.error("Usage: python -m agent_network.demo.discover_jira_transitions ISSUE-KEY")
        logger.error("Example: python -m agent_network.demo.discover_jira_transitions LST-45053")
        return 1
    if is_mock_mode():
        logger.error("Set AGENT_NETWORK_MODE=live in .env for this script.")
        return 1

    issue_key = sys.argv[1].strip()
    reset_toolset()
    jira = get_toolset().jira
    ticket = jira.get_ticket(issue_key)
    if ticket:
        logger.info("Current status: %s\n", ticket.status.value)

    details = jira.describe_transitions(issue_key)
    if not details:
        logger.info("No transitions for %s (or issue not found).", issue_key)
        return 1

    logger.info("Transitions on %s (name -> where it goes):\n", issue_key)
    for line in details:
        logger.info("  %s", line)

    closers = [d for d in details if "done" in d.lower() or "close" in d.lower()]
    if closers:
        logger.info("\nFor JIRA_DONE_TRANSITION, pick a closing transition above.")
    else:
        logger.info(
            "\nNo obvious 'close/done' transition. Options:"
            "\n  1) Open this issue in Jira UI — see if more buttons appear there"
            "\n  2) Ask mentor how to close 'Test' issues in this legacy project"
            "\n  3) Demo create+assign only (already working) until workflow is clarified"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
