"""Tests for HTTP agent-to-agent message routing."""

import os
from unittest.mock import patch

from agent_network.a2a.client import A2AClient, peer_registry
from agent_network.a2a.server import handle_a2a_request
from agent_network.mcp import get_toolset, reset_toolset
from agent_network.models import AgentMessage, AgentMessageType
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_MANAGER_ID
from agent_network.runtime import reset_runtime


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"}, clear=False)
def test_a2a_delivers_task_assign_to_recipient_twin():
    reset_toolset()
    reset_runtime()
    jira = get_toolset().jira
    ticket = jira.create_ticket("[Agent-Network-TEST] A2A task", "x", DEMO_MANAGER_ID)

    message = AgentMessage(
        sender_agent_id=f"twin-{DEMO_MANAGER_ID}",
        recipient_agent_id=f"twin-{DEMO_ASSIGNEE_ID}",
        message_type=AgentMessageType.TASK_ASSIGN,
        payload={"ticket_id": ticket.ticket_id, "title": ticket.title},
    )
    ack = handle_a2a_request(message.model_dump(mode="json"))

    assert ack["accepted"] is True
    assert ack["recipient"] == f"twin-{DEMO_ASSIGNEE_ID}"
    updated = jira.get_ticket(ticket.ticket_id)
    assert updated.assignee_id == DEMO_ASSIGNEE_ID


def test_a2a_unknown_recipient_rejected():
    reset_runtime()
    message = AgentMessage(
        sender_agent_id="twin-emp-manager",
        recipient_agent_id="twin-emp-nobody",
        message_type=AgentMessageType.TASK_ASSIGN,
        payload={},
    )
    ack = handle_a2a_request(message.model_dump(mode="json"))
    assert ack["accepted"] is False


@patch.dict(os.environ, {"A2A_PEERS": '{"twin-emp-assignee": "http://localhost:8766"}'})
def test_peer_registry_and_client_reachability():
    peers = peer_registry()
    assert peers["twin-emp-assignee"] == "http://localhost:8766"
    client = A2AClient(peers)
    assert client.can_reach("twin-emp-assignee")
    assert not client.can_reach("twin-emp-manager")
