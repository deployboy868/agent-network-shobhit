"""Smoke test for assign-and-track demo logic."""

from agent_network.bus import AgentMessageBus
from agent_network.mcp import reset_toolset
from agent_network.mcp.mock_tools import MockToolSet
from agent_network.models import TaskStatus
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_MANAGER_ID, SAMPLE_EMPLOYEES
from agent_network.twin import DigitalTwinAgent


def test_assign_and_complete():
    reset_toolset()
    tools = MockToolSet()
    bus = AgentMessageBus()
    twins = {
        e.employee_id: DigitalTwinAgent(e, bus, tools=tools) for e in SAMPLE_EMPLOYEES
    }
    reporter = twins[DEMO_MANAGER_ID]
    assignee_id = DEMO_ASSIGNEE_ID

    result = reporter.create_and_delegate_ticket(
        title="Test ticket",
        description="Test",
        assignee_employee_id=assignee_id,
    )
    assert result.success
    ticket_id = result.data["ticket_id"]

    twins[assignee_id].mark_ticket_done(ticket_id)
    status = reporter.follow_up_until_done(ticket_id, assignee_id, max_checks=5)
    assert status == TaskStatus.DONE
