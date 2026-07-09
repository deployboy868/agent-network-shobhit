"""
Smoke-test MCP tools in-process (no stdio client required).

Run:
  PYTHONPATH=. python -m agent_network.demo.verify_mcp_tools
"""

from __future__ import annotations

import json
import logging
import sys

from agent_network.mcp_server.tools_registry import call_tool, list_tool_specs

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    tools = list_tool_specs()
    logger.info("Registered %s MCP tools:\n", len(tools))
    for t in tools:
        logger.info("  - %s", t["name"])

    logger.info("\n--- agent_network_status ---")
    status = call_tool("agent_network_status", {})
    logger.info("%s", status["content"][0]["text"])

    logger.info("\n--- jira_list_tickets (read-only) ---")
    listed = call_tool("jira_list_tickets", {})
    logger.info("%s", listed["content"][0]["text"][:500])

    logger.info("\nSUCCESS — MCP tool layer works.")
    logger.info(
        "Next: add server to Cursor MCP settings and run:\n"
        "  PYTHONPATH=. python -m agent_network.mcp_server"
    )
    return 0 if not listed.get("isError") else 1


if __name__ == "__main__":
    sys.exit(main())
