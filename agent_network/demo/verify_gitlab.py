"""
List open merge requests in your GitLab project (read-only).

Run:
  PYTHONPATH=. python -m agent_network.demo.verify_gitlab
"""

from __future__ import annotations

import logging
import sys

from agent_network.mcp.live_gitlab import LiveGitLab

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    gl = LiveGitLab()
    err = gl._configured()
    if err:
        logger.error("%s", err.detail)
        return 1

    try:
        mrs = gl.list_merge_requests(state="opened", limit=10)
    except RuntimeError as e:
        logger.error("%s", e)
        return 1

    logger.info("Open merge requests (read-only, GitLab unchanged):\n")
    if not mrs:
        logger.info("  (none open in this project)")
        return 0

    for mr in mrs:
        logger.info(
            "  !%s | %s | %s",
            mr.get("iid", "?"),
            mr.get("title", "?")[:50],
            mr.get("web_url", "?"),
        )
    logger.info("\nSUCCESS — GitLab read_api works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
