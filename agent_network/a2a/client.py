"""
Client for sending agent-to-agent messages to a remote twin service over HTTP.

Peer endpoints are configured via the A2A_PEERS env var (JSON), e.g.:
  A2A_PEERS='{"twin-emp-assignee": "http://localhost:8766"}'
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agent_network.models import AgentMessage

logger = logging.getLogger(__name__)


def peer_registry() -> dict[str, str]:
    raw = os.getenv("A2A_PEERS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v).rstrip("/") for k, v in data.items()}
    except json.JSONDecodeError:
        logger.warning("A2A_PEERS is not valid JSON; ignoring")
        return {}


def send_agent_message(base_url: str, message: AgentMessage, timeout: int = 15) -> dict:
    """POST an AgentMessage to a peer twin service. Returns the ack dict."""
    url = f"{base_url.rstrip('/')}/api/a2a"
    body = json.dumps(message.model_dump(mode="json")).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return {"accepted": False, "error": f"HTTP {e.code}: {e.read().decode()}"}
    except URLError as e:
        return {"accepted": False, "error": f"connection failed: {e.reason}"}


class A2AClient:
    """Routes outbound agent messages to peers by recipient agent id."""

    def __init__(self, peers: Optional[dict[str, str]] = None) -> None:
        self.peers = peers if peers is not None else peer_registry()

    def can_reach(self, recipient_agent_id: str) -> bool:
        return recipient_agent_id in self.peers

    def send(self, message: AgentMessage) -> dict:
        base = self.peers.get(message.recipient_agent_id)
        if not base:
            return {
                "accepted": False,
                "error": f"no peer endpoint for {message.recipient_agent_id}",
            }
        return send_agent_message(base, message)
