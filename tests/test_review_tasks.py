"""Tests for read-only task review."""

import os
from unittest.mock import patch

from agent_network.bus import AgentMessageBus
from agent_network.mcp import reset_toolset
from agent_network.mcp.mock_tools import MockToolSet
from agent_network.models import TaskStatus
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_MANAGER_ID, SAMPLE_EMPLOYEES
from agent_network.twin import DigitalTwinAgent


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock"}, clear=False)
def test_review_tasks_after_create():
    reset_toolset()
    tools = MockToolSet()
    bus = AgentMessageBus()
    twins = {
        e.employee_id: DigitalTwinAgent(e, bus, tools=tools) for e in SAMPLE_EMPLOYEES
    }
    reporter = twins[DEMO_MANAGER_ID]

    reporter.create_and_delegate_ticket(
        title="[TEST] Review me",
        description="test",
        assignee_employee_id=DEMO_ASSIGNEE_ID,
    )

    report = reporter.review_tasks()
    assert report.total >= 1
