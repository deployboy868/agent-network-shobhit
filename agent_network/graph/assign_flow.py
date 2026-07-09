"""
LangGraph state machine for assign-and-track demo.

Same steps as assign_and_track.py, but orchestrated as an explicit graph:
  delegate → complete → track → END
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agent_network.twin import DigitalTwinAgent


class AssignFlowState(TypedDict, total=False):
    title: str
    description: str
    assignee_employee_id: str
    ticket_id: str
    delegation_ok: bool
    close_ok: bool
    final_status: str
    error: str


def build_assign_flow_graph(
    reporter: DigitalTwinAgent,
    assignee: DigitalTwinAgent,
):
    """Compile a graph that runs the internship assign-and-track workflow."""

    def delegate(state: AssignFlowState) -> AssignFlowState:
        if state.get("error"):
            return {}
        try:
            result = reporter.create_and_delegate_ticket(
                title=state["title"],
                description=state["description"],
                assignee_employee_id=state["assignee_employee_id"],
            )
        except RuntimeError as e:
            return {"error": str(e), "delegation_ok": False}
        if not result.success:
            return {"error": result.detail, "delegation_ok": False}
        return {
            "ticket_id": result.data["ticket_id"],
            "delegation_ok": True,
        }

    def complete(state: AssignFlowState) -> AssignFlowState:
        if state.get("error"):
            return {}
        try:
            result = assignee.mark_ticket_done(state["ticket_id"])
        except RuntimeError as e:
            return {"error": str(e), "close_ok": False}
        if not result.success:
            return {"error": result.detail, "close_ok": False}
        return {"close_ok": True}

    def track(state: AssignFlowState) -> AssignFlowState:
        if state.get("error"):
            return {}
        status = reporter.follow_up_until_done(
            state["ticket_id"],
            state["assignee_employee_id"],
        )
        return {"final_status": status.value}

    def after_delegate(state: AssignFlowState) -> str:
        return "complete" if state.get("delegation_ok") else END

    def after_complete(state: AssignFlowState) -> str:
        return "track" if state.get("close_ok") else END

    graph = StateGraph(AssignFlowState)
    graph.add_node("delegate", delegate)
    graph.add_node("complete", complete)
    graph.add_node("track", track)
    graph.add_edge(START, "delegate")
    graph.add_conditional_edges(
        "delegate",
        after_delegate,
        {"complete": "complete", END: END},
    )
    graph.add_conditional_edges(
        "complete",
        after_complete,
        {"track": "track", END: END},
    )
    graph.add_edge("track", END)
    return graph.compile()


def run_assign_flow(
    reporter: DigitalTwinAgent,
    assignee: DigitalTwinAgent,
    *,
    title: str,
    description: str,
    assignee_employee_id: str,
) -> AssignFlowState:
    """Run the compiled graph and return final state."""
    app = build_assign_flow_graph(reporter, assignee)
    return app.invoke(
        {
            "title": title,
            "description": description,
            "assignee_employee_id": assignee_employee_id,
        }
    )
