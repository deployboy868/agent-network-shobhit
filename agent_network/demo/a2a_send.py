"""
Send a real agent-to-agent message to a peer twin service over HTTP.

Run a server first (see a2a_server.py), then:
  PYTHONPATH=. python -m agent_network.demo.a2a_send \
    --url http://localhost:8766 --ticket JIRA-DEMO1234
"""

from __future__ import annotations

import argparse
import json

from agent_network.a2a.client import send_agent_message
from agent_network.models import AgentMessage, AgentMessageType
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_MANAGER_ID


def main() -> int:
    parser = argparse.ArgumentParser(description="Send A2A TASK_ASSIGN over HTTP")
    parser.add_argument("--url", default="http://localhost:8766")
    parser.add_argument("--ticket", default="JIRA-DEMO1234")
    parser.add_argument("--title", default="[Agent-Network-TEST] Cross-service delegation")
    args = parser.parse_args()

    message = AgentMessage(
        sender_agent_id=f"twin-{DEMO_MANAGER_ID}",
        recipient_agent_id=f"twin-{DEMO_ASSIGNEE_ID}",
        message_type=AgentMessageType.TASK_ASSIGN,
        payload={"ticket_id": args.ticket, "title": args.title, "description": args.title},
    )
    ack = send_agent_message(args.url, message)
    print(json.dumps(ack, indent=2))
    return 0 if ack.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
