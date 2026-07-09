"""
List issue types you can create in your Jira project.

Needs in .env: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY

Run:
  PYTHONPATH=. python -m agent_network.demo.discover_jira_issue_types
"""

from __future__ import annotations

import base64
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
    try:
        base = config.jira_base_url()
        email = config.jira_email()
        token = config.jira_api_token()
        project = config.jira_project_key()
    except ValueError as e:
        logger.error("%s", e)
        return 1

    auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
    url = (
        f"{base}/rest/api/3/issue/createmeta"
        f"?projectKeys={quote(project)}&expand=projects.issuetypes"
    )
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

    projects = data.get("projects", [])
    if not projects:
        logger.info("No create metadata for project %s. Check JIRA_PROJECT_KEY.", project)
        return 1

    types = projects[0].get("issuetypes", [])
    creatable = [t for t in types if not t.get("subtask")]
    if not creatable:
        logger.info("No issue types found for project %s.", project)
        return 1

    current = config.jira_issue_type()
    logger.info("Issue types you can CREATE in project %s:\n", project)
    for t in creatable:
        name = t.get("name", "?")
        marker = "  <-- set JIRA_ISSUE_TYPE to this" if name == current else ""
        logger.info("  %s%s", name, marker)
    logger.info(
        "\nYour .env has JIRA_ISSUE_TYPE=%s — pick an exact name from the list above.",
        current,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
