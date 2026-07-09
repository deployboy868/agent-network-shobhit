"""
Agent bus with an HTTP transport: messages to peers configured in A2A_PEERS are
delivered over the network to a remote twin service; everyone else is delivered
in-process. This lets twins truly run as separate services and coordinate.
"""

from __future__ import annotations

import logging

from agent_network.a2a.client import A2AClient
from agent_network.bus import AgentMessageBus
from agent_network.models import AgentMessage

logger = logging.getLogger(__name__)


class HttpAgentBus(AgentMessageBus):
    def __init__(self) -> None:
        super().__init__()
        self.client = A2AClient()

    def send(self, message: AgentMessage) -> None:
        if self.client.can_reach(message.recipient_agent_id):
            ack = self.client.send(message)
            if not ack.get("accepted"):
                logger.warning(
                    "A2A remote delivery failed for %s: %s",
                    message.recipient_agent_id,
                    ack.get("error"),
                )
            # Keep a local copy for inspection / follow-up polling.
            self._inbox[message.recipient_agent_id].append(message)
            return
        super().send(message)
