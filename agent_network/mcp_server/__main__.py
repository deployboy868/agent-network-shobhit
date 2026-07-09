"""Run Agent Network MCP server (stdio)."""

from __future__ import annotations

import logging
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Log outside the project folder — Cursor restarts MCP when project files change.
_LOG = Path(os.path.expanduser("~/.agent-network-mcp.log"))


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        filename=str(_LOG),
        filemode="a",
    )


def main() -> None:
    _configure_logging()
    logging.info("MCP server process starting")
    try:
        from agent_network.mcp_server.server import run_stdio

        run_stdio()
    except Exception:
        logging.exception("MCP server crashed")
        raise
    finally:
        logging.info("MCP server process exiting")


if __name__ == "__main__":
    main()
