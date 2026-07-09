"""
Dry-run GitLab write APIs (creates a real branch, commit, and MR).

Run only against your personal demo repo:
  PYTHONPATH=. python -m agent_network.demo.verify_gitlab_write
"""

from __future__ import annotations

import logging
import sys
import time

from agent_network.mcp.live_gitlab import LiveGitLab

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    gl = LiveGitLab()
    err = gl._configured()
    if err:
        logger.error("%s", err.detail)
        return 1

    ticket_id = f"VERIFY-{int(time.time())}"
    title = f"[Agent-Network-TEST] Verify write path {ticket_id}"
    description = "Automated verify script — safe to close/delete."

    logger.info("Creating MR from ticket sub-agent flow...")
    result = gl.create_mr_from_ticket(ticket_id, title, description)
    if not result.success:
        logger.error("FAILED: %s", result.detail)
        return 1

    mr_url = (result.data or {}).get("mr_url", "")
    logger.info("SUCCESS — %s", result.detail)
    if mr_url:
        logger.info("MR URL: %s", mr_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
