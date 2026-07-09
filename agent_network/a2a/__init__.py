"""Real agent-to-agent communication over HTTP (cross-process / cross-service)."""

from agent_network.a2a.client import A2AClient, peer_registry, send_agent_message
from agent_network.a2a.server import handle_a2a_request, run_server

__all__ = [
    "A2AClient",
    "peer_registry",
    "send_agent_message",
    "handle_a2a_request",
    "run_server",
]
