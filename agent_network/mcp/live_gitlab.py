"""GitLab REST API client — read MRs; create branch/commit/MR from Jira tickets."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from agent_network import config
from agent_network.models import AgentActionResult
from agent_network.mcp.base import GitLabTools
from agent_network.workers.mr_from_ticket import generate_task_artifact

logger = logging.getLogger(__name__)


class LiveGitLab(GitLabTools):
    """List MRs; create MR from ticket; link MR to Jira (comment on Jira)."""

    def __init__(self, jira: Optional[Any] = None) -> None:
        self._base = config.gitlab_base_url()
        self._token = config.gitlab_private_token()
        self._project_id = config.gitlab_project_id()
        self._jira = jira

    def _configured(self) -> Optional[AgentActionResult]:
        if not self._base or not self._token:
            return AgentActionResult(
                success=False,
                detail="Set GITLAB_BASE_URL and GITLAB_PRIVATE_TOKEN in .env",
            )
        if not self._project_id:
            return AgentActionResult(
                success=False,
                detail="Set GITLAB_PROJECT_ID in .env (from discover_gitlab_projects)",
            )
        return None

    def _project_path(self) -> str:
        return quote(self._project_id, safe="")

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self._base}/api/v4{path}"
        data = None
        headers = {
            "PRIVATE-TOKEN": self._token,
            "Accept": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            err_body = e.read().decode()
            raise RuntimeError(f"GitLab API error {e.code}: {err_body}") from e

    def get_default_branch(self) -> str:
        configured = config.gitlab_default_branch()
        if configured:
            return configured
        data = self._request("GET", f"/projects/{self._project_path()}")
        return str(data.get("default_branch") or "main")

    def list_merge_requests(self, state: str = "opened", limit: int = 10) -> list[dict[str, Any]]:
        """Read-only list of MRs in configured project."""
        err = self._configured()
        if err:
            raise RuntimeError(err.detail)
        data = self._request(
            "GET",
            f"/projects/{self._project_path()}/merge_requests?state={state}&per_page={limit}",
        )
        return data if isinstance(data, list) else []

    def _branch_name_for_ticket(self, ticket_id: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", ticket_id).strip("-").lower()
        suffix = int(time.time()) % 100000
        return f"agent-network/{slug}-{suffix}"

    def create_branch(self, branch_name: str, ref: str) -> dict[str, Any]:
        err = self._configured()
        if err:
            raise RuntimeError(err.detail)
        return self._request(
            "POST",
            f"/projects/{self._project_path()}/repository/branches",
            {"branch": branch_name, "ref": ref},
        )

    def create_commit(
        self,
        branch_name: str,
        message: str,
        file_path: str,
        file_content: str,
    ) -> dict[str, Any]:
        err = self._configured()
        if err:
            raise RuntimeError(err.detail)
        return self._request(
            "POST",
            f"/projects/{self._project_path()}/repository/commits",
            {
                "branch": branch_name,
                "commit_message": message,
                "actions": [
                    {
                        "action": "create",
                        "file_path": file_path,
                        "content": file_content,
                    }
                ],
            },
        )

    def create_merge_request(
        self,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        err = self._configured()
        if err:
            raise RuntimeError(err.detail)
        return self._request(
            "POST",
            f"/projects/{self._project_path()}/merge_requests",
            {
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
                "remove_source_branch": True,
            },
        )

    def create_mr_from_ticket(
        self,
        ticket_id: str,
        title: str,
        description: str = "",
    ) -> AgentActionResult:
        """
        Sub-agent flow: Groq (or fallback) → branch → commit → MR → Jira link.
        """
        err = self._configured()
        if err:
            return err

        safe_prefix = config.jira_safe_prefix()
        if safe_prefix and safe_prefix not in (title or ""):
            return AgentActionResult(
                success=False,
                detail=(
                    f"Ticket title must include safe prefix '{safe_prefix}' "
                    f"before opening a GitLab MR."
                ),
            )

        try:
            artifact = generate_task_artifact(ticket_id, title, description)
            target = self.get_default_branch()
            branch = self._branch_name_for_ticket(ticket_id)
            self.create_branch(branch, target)

            commit_msg = f"[Agent-Network] {ticket_id}: {artifact['summary']}"
            self.create_commit(
                branch,
                commit_msg,
                artifact["file_path"],
                artifact["file_content"],
            )

            mr_title = f"{safe_prefix} {ticket_id}: {artifact['summary']}".strip()
            mr_body = (
                f"Auto-generated from Jira ticket **{ticket_id}**.\n\n"
                f"**Original title:** {title}\n\n"
                f"**File:** `{artifact['file_path']}`\n\n"
                f"_{artifact['summary']}_"
            )
            mr = self.create_merge_request(branch, target, mr_title, mr_body)
            mr_url = str(mr.get("web_url") or "")
            if not mr_url:
                return AgentActionResult(
                    success=False,
                    detail="MR created but web_url missing from GitLab response.",
                    data={"mr": mr},
                )

            link = self.link_mr_to_ticket(ticket_id, mr_url)
            if not link.success:
                return AgentActionResult(
                    success=True,
                    detail=(
                        f"Opened MR {mr_url} but Jira link failed: {link.detail}"
                    ),
                    data={
                        "ticket_id": ticket_id,
                        "mr_url": mr_url,
                        "mr_iid": mr.get("iid"),
                        "branch": branch,
                        "file_path": artifact["file_path"],
                    },
                )

            return AgentActionResult(
                success=True,
                detail=f"Opened GitLab MR and linked to {ticket_id}: {mr_url}",
                data={
                    "ticket_id": ticket_id,
                    "mr_url": mr_url,
                    "mr_iid": mr.get("iid"),
                    "branch": branch,
                    "file_path": artifact["file_path"],
                },
            )
        except RuntimeError as e:
            return AgentActionResult(success=False, detail=str(e))

    def link_mr_to_ticket(self, ticket_id: str, mr_url: str) -> AgentActionResult:
        """
        Verify MR exists (read-only), then add link as Jira comment (not GitLab write).
        """
        err = self._configured()
        if err:
            return err
        try:
            mrs = self.list_merge_requests(state="all", limit=50)
        except RuntimeError as e:
            return AgentActionResult(success=False, detail=str(e))

        match = None
        for mr in mrs:
            if mr.get("web_url") == mr_url or mr_url.rstrip("/") in (mr.get("web_url") or ""):
                match = mr
                break

        if not match:
            return AgentActionResult(
                success=False,
                detail=f"MR not found in project {self._project_id}: {mr_url}",
            )

        if self._jira is None:
            return AgentActionResult(
                success=True,
                detail="MR verified (read-only). Jira link skipped — no Jira client.",
                data={"mr_url": mr_url, "mr_iid": match.get("iid")},
            )

        comment = f"[Agent-Network] Linked GitLab MR: {mr_url}"
        result = self._jira.add_comment(ticket_id, comment)
        if not result.success:
            return result
        return AgentActionResult(
            success=True,
            detail=f"Linked MR to {ticket_id} via Jira comment (GitLab unchanged)",
            data={"ticket_id": ticket_id, "mr_url": mr_url, "mr_iid": match.get("iid")},
        )
