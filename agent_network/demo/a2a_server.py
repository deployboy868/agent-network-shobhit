"""
Run a twin service that accepts agent-to-agent messages over HTTP.

Example (two terminals):
  # Terminal 1 — assignee's twin service
  PYTHONPATH=. python -m agent_network.demo.a2a_server --port 8766

  # Terminal 2 — send a delegation from manager to assignee over HTTP
  A2A_PEERS='{"twin-emp-assignee":"http://localhost:8766"}' \
    PYTHONPATH=. python -m agent_network.demo.a2a_send
"""

from __future__ import annotations

import argparse

from agent_network.a2a.server import run_server


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent-to-agent HTTP twin service")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
