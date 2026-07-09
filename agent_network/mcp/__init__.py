"""MCP-style tool layer: mock implementations first, live adapters later."""

from __future__ import annotations

from typing import Optional

from agent_network.config import is_mock_mode
from agent_network.mcp.base import ToolSet
from agent_network.mcp.mock_tools import MockToolSet

__all__ = ["get_toolset", "reset_toolset", "ToolSet", "MockToolSet"]

_shared_toolset: Optional[ToolSet] = None


def get_toolset() -> ToolSet:
    """Return one shared toolset per process so all agents see the same mock Jira data."""
    global _shared_toolset
    if _shared_toolset is not None:
        return _shared_toolset
    if is_mock_mode():
        _shared_toolset = MockToolSet()
    else:
        from agent_network.mcp.live_toolset import LiveToolSet

        _shared_toolset = LiveToolSet()
    return _shared_toolset


def reset_toolset() -> None:
    """Clear cached toolset (useful in tests)."""
    global _shared_toolset
    _shared_toolset = None
