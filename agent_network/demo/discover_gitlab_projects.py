"""
List GitLab projects visible to your token — no browser UI needed.

Needs in .env: GITLAB_BASE_URL, GITLAB_PRIVATE_TOKEN
Does NOT need: GITLAB_PROJECT_ID

Run:
  PYTHONPATH=. python -m agent_network.demo.discover_gitlab_projects
"""

from __future__ import annotations

import json
import logging
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from agent_network import config

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    base = config.gitlab_base_url()
    token = config.gitlab_private_token()
    if not base or not token:
        logger.error("Set GITLAB_BASE_URL and GITLAB_PRIVATE_TOKEN in .env first.")
        return 1

    url = f"{base}/api/v4/projects?membership=true&simple=true&per_page=50"
    req = Request(
        url,
        headers={"PRIVATE-TOKEN": token, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            projects = json.loads(resp.read().decode())
    except HTTPError as e:
        body = e.read().decode()
        logger.error("GitLab HTTP %s: %s", e.code, body)
        if e.code in (401, 403):
            logger.error(
                "Token works but access may be blocked. Ask mentor for a test project ID/path."
            )
        return 1

    if not projects:
        logger.info("No projects returned. Ask mentor for GITLAB_PROJECT_ID (sandbox).")
        return 0

    logger.info("Projects your token can see (use 'id' as GITLAB_PROJECT_ID):\n")
    for p in projects:
        pid = p.get("id", "?")
        path = p.get("path_with_namespace", "?")
        name = p.get("name", "?")
        logger.info("  %s  —  %s  (%s)", pid, path, name)
    logger.info("\nAdd to .env: GITLAB_PROJECT_ID=<id above>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
