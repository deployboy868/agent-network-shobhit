"""Shared in-process runtime: message bus + digital twins.

If A2A_PEERS is configured, the bus uses an HTTP transport so messages to peer
twins are delivered over the network to remote twin services.
"""

from __future__ import annotations

import os
from typing import Optional

from agent_network.bus import AgentMessageBus
from agent_network.registry import SAMPLE_EMPLOYEES
from agent_network.twin import DigitalTwinAgent

_bus: Optional[AgentMessageBus] = None
_twins: Optional[dict[str, DigitalTwinAgent]] = None


def _make_bus() -> AgentMessageBus:
    if os.getenv("A2A_PEERS", "").strip():
        from agent_network.a2a.network_bus import HttpAgentBus

        return HttpAgentBus()
    return AgentMessageBus()


def get_runtime() -> tuple[AgentMessageBus, dict[str, DigitalTwinAgent]]:
    """Return singleton bus and twins (shared by MCP delegate + chat demos)."""
    global _bus, _twins
    if _bus is None or _twins is None:
        bus = _make_bus()
        twins = {emp.employee_id: DigitalTwinAgent(emp, bus) for emp in SAMPLE_EMPLOYEES}
        _bus = bus
        _twins = twins
    return _bus, _twins


def reset_runtime() -> None:
    """Clear runtime (for tests)."""
    global _bus, _twins
    _bus = None
    _twins = None
