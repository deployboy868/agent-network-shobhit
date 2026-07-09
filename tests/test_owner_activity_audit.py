"""Owner activity summary must reflect ticket creates from stand-in audit log."""

import os
import tempfile
from unittest.mock import patch

from agent_network.agent.twin_chat import TwinChatSession
from agent_network.audit import log_twin_action
from agent_network.mcp import reset_toolset
from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID
from agent_network.runtime import reset_runtime
from agent_network.standin_policy import reset_standin_policies


def _temp_audit():
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    tmp.close()
    return patch.dict(os.environ, {"TWIN_AUDIT_LOG": tmp.name})


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "ollama"})
def test_owner_activity_reports_ticket_created_for_intern():
    """LLM must not override audit facts — intern ticket create must appear."""
    with _temp_audit():
        reset_toolset()
        reset_runtime()
        reset_standin_policies()

        log_twin_action(
            twin_employee_id=DEMO_MANAGER_ID,
            action="twin_create_ticket_for_requester",
            detail="Created JIRA-DEMO99 for Demo Intern",
            data={
                "ticket_id": "JIRA-DEMO99",
                "requester_employee_id": DEMO_INTERN_ID,
                "title": "[Agent-Network-TEST] Sprint Planner",
            },
        )

        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        reply = owner.handle("what happened while I was away?")

        assert "JIRA-DEMO99" in reply
        assert "demo intern" in reply.lower()
        assert "tickets created for colleagues (1)" in reply.lower()


@patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"})
def test_owner_assign_query_includes_created_tickets():
    with _temp_audit():
        reset_toolset()
        reset_runtime()
        reset_standin_policies()

        log_twin_action(
            twin_employee_id=DEMO_MANAGER_ID,
            action="twin_create_ticket_for_requester",
            detail="Created JIRA-DEMO88 for Demo Intern",
            data={
                "ticket_id": "JIRA-DEMO88",
                "requester_employee_id": DEMO_INTERN_ID,
            },
        )

        owner = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_MANAGER_ID)
        reply = owner.handle("did you assign anyone tickets?")

        assert "JIRA-DEMO88" in reply
        assert "yes" in reply.lower()
