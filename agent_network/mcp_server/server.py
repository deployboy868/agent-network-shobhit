"""Agent Network MCP server — stdio transport for Cursor / Copilot clients."""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional

from agent_network.mcp_server.protocol import read_message, write_error, write_response

logger = logging.getLogger(__name__)

SERVER_NAME = "agent-network"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"


def _tools():
    from agent_network.mcp_server.tools_registry import call_tool, list_tool_specs

    return call_tool, list_tool_specs


def dispatch(method: str, params: dict[str, Any]) -> Any:
    if method == "initialize":
        client_proto = params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION)
        return {
            "protocolVersion": client_proto,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {},
                "prompts": {},
            },
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    if method in ("ping", "ping/"):
        return {}
    call_tool, list_tool_specs = _tools()
    if method == "tools/list":
        return {"tools": list_tool_specs()}
    if method == "resources/list":
        return {"resources": []}
    if method == "prompts/list":
        return {"prompts": []}
    if method == "tools/call":
        return call_tool(params.get("name", ""), params.get("arguments") or {})
    raise ValueError(f"Method not found: {method}")


def run_stdio() -> None:
    """Run MCP server on stdin/stdout. Never write logs to stderr (breaks MCP)."""
    logger.info("Entering MCP read loop")
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        try:
            message: Optional[dict[str, Any]] = read_message(stdin)
        except Exception as e:
            logger.warning("Failed to read MCP message: %s", e)
            continue

        if message is None:
            logger.info("stdin closed — exiting")
            break

        method = message.get("method", "")
        req_id = message.get("id")
        params = message.get("params") or {}
        logger.info("MCP request: %s id=%s", method, req_id)

        if method.startswith("notifications/"):
            continue

        if req_id is None:
            continue

        try:
            result = dispatch(method, params)
            write_response(stdout, req_id, result)
            logger.info("MCP response ok: %s", method)
        except ValueError as e:
            logger.warning("MCP method not found: %s", method)
            write_error(stdout, req_id, -32601, str(e))
        except Exception as e:
            logger.exception("Request failed: %s", method)
            write_error(stdout, req_id, -32603, str(e))
