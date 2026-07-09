"""
List Jira projects you can access — helps find JIRA_PROJECT_KEY without asking mentor.

Needs in .env: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
Does NOT need: JIRA_PROJECT_KEY

Run:
  PYTHONPATH=. python -m agent_network.demo.discover_jira_projects
"""

from __future__ import annotations

import base64
import json
import logging
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent_network import config

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        base = config.jira_base_url()
        email = config.jira_email()
        token = config.jira_api_token()
    except ValueError as e:
        logger.error("%s", e)
        logger.error("Fill JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN in .env first.")
        return 1

    auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
    url = f"{base}/rest/api/3/project/search?maxResults=50"
    req = Request(
        url,
        headers={"Authorization": auth, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except HTTPError as e:
        logger.error("Jira returned HTTP %s: %s", e.code, e.read().decode())
        return 1

    values = data.get("values", [])
    if not values:
        logger.info("No projects returned. Ask mentor which sandbox you can use.")
        return 0

    logger.info("Projects you can see (use 'key' as JIRA_PROJECT_KEY):\n")
    for p in values:
        key = p.get("key", "?")
        name = p.get("name", "?")
        logger.info("  %s  —  %s", key, name)
    logger.info("\nCopy the right key into .env as JIRA_PROJECT_KEY=...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
