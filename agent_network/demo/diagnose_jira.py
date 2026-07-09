"""
Check Jira API credentials (separate from browser login).

Run:
  PYTHONPATH=. python -m agent_network.demo.diagnose_jira
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


def _auth_header() -> str:
    email = config.jira_email()
    token = config.jira_api_token()
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def _get(base: str, path: str) -> tuple[int, str]:
    req = Request(
        f"{base}{path}",
        headers={"Authorization": _auth_header(), "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    try:
        base = config.jira_base_url()
        email = config.jira_email()
        project = config.jira_project_key()
    except ValueError as e:
        logger.error("%s", e)
        return 1

    logger.info("Jira API diagnostic\n")
    logger.info(".env JIRA_EMAIL: %s", email)
    logger.info(".env JIRA_PROJECT_KEY: %s\n", project)

    code, body = _get(base, "/rest/api/3/myself")
    if code == 200:
        me = json.loads(body)
        logger.info("✓ API auth OK — logged in as: %s", me.get("displayName"))
        logger.info("  email: %s", me.get("emailAddress"))
    elif code == 401:
        logger.error("✗ API auth FAILED (401 Unauthorized)")
        logger.error(
            "Your browser can still open Jira, but the API token in .env is "
            "invalid or expired.\n"
        )
        logger.error("Fix:")
        logger.error("  1. https://id.atlassian.com/manage-profile/security/api-tokens")
        logger.error("  2. Create new token → paste into JIRA_API_TOKEN in .env")
        logger.error("  3. JIRA_EMAIL must match your Atlassian account exactly")
        logger.error("  4. Save .env, then: PYTHONPATH=. python -m agent_network.demo.verify_jira")
        return 1
    else:
        logger.error("✗ GET /myself returned HTTP %s: %s", code, body[:200])
        return 1

    code, body = _get(base, "/rest/api/3/issue/LST-45492?fields=summary,project")
    if code == 200:
        issue = json.loads(body)
        logger.info("\n✓ Can read LST-45492 via API")
        logger.info("  %s", issue.get("fields", {}).get("summary", "")[:60])
    else:
        logger.info("\n? Cannot read LST-45492 via API (HTTP %s)", code)

    code, body = _get(
        base,
        f"/rest/api/3/issue/createmeta?projectKeys={project}&expand=projects.issuetypes",
    )
    if code == 200:
        meta = json.loads(body)
        projects = meta.get("projects", [])
        if projects:
            types = [t["name"] for t in projects[0].get("issuetypes", [])]
            logger.info("\n✓ Can create issues in %s — types: %s", project, types)
            it = config.jira_issue_type()
            if it not in types:
                logger.warning("  JIRA_ISSUE_TYPE=%s not in list — update .env", it)
        else:
            logger.error("\n✗ No create permission for project %s via API", project)
    else:
        logger.error("\n✗ createmeta HTTP %s", code)

    logger.info("\nNext: PYTHONPATH=. python -m agent_network.demo.verify_jira")
    return 0


if __name__ == "__main__":
    sys.exit(main())
