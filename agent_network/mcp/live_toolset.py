"""Live Jira + mock tools for everything else (until those APIs are wired)."""

from __future__ import annotations

from agent_network.mcp.base import ToolSet
from agent_network.mcp.live_gitlab import LiveGitLab
from agent_network.mcp.live_jira import LiveJira
from agent_network.mcp.mock_tools import MockTeams, MockWorkday


class LiveToolSet(ToolSet):
    def __init__(self) -> None:
        self.jira = LiveJira()
        self.gitlab = LiveGitLab(jira=self.jira)
        self.teams = MockTeams()
        self.workday = MockWorkday()
