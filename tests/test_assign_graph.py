"""LangGraph assign flow in mock mode."""

from agent_network.bus import AgentMessageBus
from agent_network.graph.assign_flow import run_assign_flow
from agent_network.mcp import reset_toolset
from agent_network.mcp.mock_tools import MockToolSet
from agent_network.models import TaskStatus
from agent_network.registry import DEMO_ASSIGNEE_ID, DEMO_MANAGER_ID, SAMPLE_EMPLOYEES
from agent_network.twin import DigitalTwinAgent


def test_langgraph_assign_flow():
    reset_toolset()
    tools = MockToolSet()
    bus = AgentMessageBus()
    twins = {
        e.employee_id: DigitalTwinAgent(e, bus, tools=tools) for e in SAMPLE_EMPLOYEES
    }
    reporter = twins[DEMO_MANAGER_ID]
    assignee_id = DEMO_ASSIGNEE_ID

    state = run_assign_flow(
        reporter,
        twins[assignee_id],
        title="Graph test ticket",
        description="LangGraph smoke test",
        assignee_employee_id=assignee_id,
    )

    assert not state.get("error")
    assert state.get("delegation_ok")
    assert state.get("close_ok")
    assert state.get("final_status") == TaskStatus.DONE.value
