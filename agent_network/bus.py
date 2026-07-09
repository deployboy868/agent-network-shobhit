"""In-process agent-to-agent message bus (protocol MVP)."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from agent_network.models import AgentMessage

MessageHandler = Callable[[AgentMessage], None]


class AgentMessageBus:
    """
    Simple pub/sub bus: agents register handlers; send delivers to recipient inbox.
    Later this can become HTTP, queues, or LangGraph channels.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._inbox: dict[str, list[AgentMessage]] = defaultdict(list)

    def register(self, agent_id: str, handler: MessageHandler) -> None:
        self._handlers[agent_id].append(handler)

    def send(self, message: AgentMessage) -> None:
        self._inbox[message.recipient_agent_id].append(message)
        for handler in self._handlers.get(message.recipient_agent_id, []):
            handler(message)

    def inbox_for(self, agent_id: str) -> list[AgentMessage]:
        return list(self._inbox.get(agent_id, []))
