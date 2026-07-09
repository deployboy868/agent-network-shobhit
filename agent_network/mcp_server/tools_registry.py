"""MCP tool definitions and handlers (wraps agent_network.mcp toolset)."""

from __future__ import annotations

import json
from typing import Any, Callable

from agent_network.audit import log_twin_action
from agent_network.config import is_demo_safe_mode, is_mock_mode, jira_email
from agent_network.mcp import get_toolset
from agent_network.models import AgentActionResult, TaskStatus
from agent_network.notify import notify_twin_owner
from agent_network.registry import employee_by_id, employee_display_name
from agent_network.runtime import get_runtime
from agent_network.standin_policy import get_policy

ToolHandler = Callable[[dict[str, Any]], Any]

_TOOLS: list[dict[str, Any]] = []
_HANDLERS: dict[str, ToolHandler] = {}


def _register(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    handler: ToolHandler,
) -> None:
    _TOOLS.append(
        {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
    )
    _HANDLERS[name] = handler


def list_tool_specs() -> list[dict[str, Any]]:
    return list(_TOOLS)


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in _HANDLERS:
        return _tool_error(f"Unknown tool: {name}")
    try:
        result = _HANDLERS[name](arguments or {})
        return _tool_ok(result)
    except RuntimeError as e:
        return _tool_error(str(e))
    except Exception as e:
        return _tool_error(f"{type(e).__name__}: {e}")


def _tool_ok(payload: Any) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _tools() -> Any:
    return get_toolset()


def _result_payload(result: AgentActionResult) -> dict[str, Any]:
    return {"success": result.success, "detail": result.detail, "data": result.data}


def _register_all() -> None:
    if _TOOLS:
        return

    _register(
        "jira_create_ticket",
        "Create a Jira ticket with [Agent-Network-TEST] safe prefix. Live mode only.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "reporter_id": {
                    "type": "string",
                    "description": "Employee id from registry (e.g. emp-manager)",
                },
            },
            "required": ["title", "description"],
        },
        lambda args: _handle_jira_create(args),
    )

    _register(
        "jira_get_ticket",
        "Read one Jira ticket by key (e.g. LST-46547).",
        {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
        },
        lambda args: _handle_jira_get(args),
    )

    _register(
        "jira_list_tickets",
        "List demo tickets (read-only). Live mode filters to [Agent-Network-TEST] prefix.",
        {
            "type": "object",
            "properties": {
                "assignee_email": {
                    "type": "string",
                    "description": "Optional; defaults to you in demo safe mode",
                },
            },
        },
        lambda args: _handle_jira_list(args),
    )

    _register(
        "jira_assign_ticket",
        "Assign ticket to an employee. Demo safe mode assigns to JIRA_EMAIL only.",
        {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "assignee_employee_id": {
                    "type": "string",
                    "description": "Registry id e.g. emp-assignee",
                },
            },
            "required": ["ticket_id", "assignee_employee_id"],
        },
        lambda args: _handle_jira_assign(args),
    )

    _register(
        "jira_mark_ticket_done",
        "Walk Jira workflow to done/closed (safe-prefix tickets only).",
        {
            "type": "object",
            "properties": {"ticket_id": {"type": "string"}},
            "required": ["ticket_id"],
        },
        lambda args: _handle_jira_done(args),
    )

    _register(
        "gitlab_list_merge_requests",
        "List merge requests in configured GitLab project (read-only GET).",
        {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "opened, closed, merged, or all",
                },
                "limit": {"type": "integer", "description": "Max MRs to return (default 10)"},
            },
            "additionalProperties": False,
        },
        lambda args: _handle_gitlab_list_mrs(args),
    )

    _register(
        "gitlab_link_mr_to_ticket",
        "Verify MR exists (read-only), add link as Jira comment (no GitLab write).",
        {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "mr_url": {"type": "string"},
            },
            "required": ["ticket_id", "mr_url"],
        },
        lambda args: _handle_gitlab_link(args),
    )

    _register(
        "gitlab_create_mr_from_ticket",
        (
            "Owner-only sub-agent: read Jira ticket, generate a small file change "
            "(Groq), open a GitLab merge request, and link it to the ticket."
        ),
        {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "Jira key e.g. LST-12345"},
            },
            "required": ["ticket_id"],
        },
        lambda args: _handle_gitlab_create_mr_from_ticket(args),
    )

    _register(
        "teams_notify_user",
        "Notify user via Teams (mock unless live Teams is configured).",
        {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["email", "message"],
        },
        lambda args: _handle_teams_notify(args),
    )

    _register(
        "workday_get_employee_manager",
        "Look up employee manager (mock unless Workday live).",
        {
            "type": "object",
            "properties": {"employee_id": {"type": "string"}},
            "required": ["employee_id"],
        },
        lambda args: _handle_workday_manager(args),
    )

    _register(
        "twin_create_ticket_for_requester",
        (
            "Create a Jira ticket assigned to the person asking (their board). "
            "Use when they want work tracked for themselves — NOT delegation to someone else."
        ),
        {
            "type": "object",
            "properties": {
                "twin_employee_id": {
                    "type": "string",
                    "description": "Registry id of twin owner (e.g. emp-manager)",
                },
                "requester_employee_id": {
                    "type": "string",
                    "description": "Registry id of person asking (ticket assignee)",
                },
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["twin_employee_id", "requester_employee_id", "title"],
        },
        lambda args: _handle_twin_create_for_requester(args),
    )

    _register(
        "twin_delegate_ticket",
        (
            "Owner-only: create a Jira ticket and delegate to another employee's twin "
            "via the agent bus. Requires the twin owner to invoke while absent."
        ),
        {
            "type": "object",
            "properties": {
                "reporter_employee_id": {
                    "type": "string",
                    "description": "Registry id of twin acting on behalf of user (e.g. emp-manager)",
                },
                "invoker_employee_id": {
                    "type": "string",
                    "description": "Must match reporter — only the twin owner may delegate.",
                },
                "assignee_employee_id": {
                    "type": "string",
                    "description": "Registry id to delegate to (e.g. emp-assignee)",
                },
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": [
                "reporter_employee_id",
                "invoker_employee_id",
                "assignee_employee_id",
                "title",
            ],
        },
        lambda args: _handle_twin_delegate(args),
    )

    _register(
        "agent_network_status",
        "Show mode (mock/live) and active safety settings.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        lambda _args: _handle_status(),
    )

    _register(
        "twin_get_stand_in_activity",
        (
            "Owner-only: read stand-in audit log — tickets created/delegated and other "
            "actions while the owner was away. Call before answering activity questions."
        ),
        {
            "type": "object",
            "properties": {
                "twin_employee_id": {
                    "type": "string",
                    "description": "Registry id of twin owner (e.g. emp-manager)",
                },
            },
            "required": ["twin_employee_id"],
        },
        lambda args: _handle_twin_get_stand_in_activity(args),
    )

    _register(
        "twin_get_colleague_chat",
        (
            "Owner-only: fetch stand-in chat transcript with one colleague. "
            "Use when owner asks what someone said (intern, assignee, etc.)."
        ),
        {
            "type": "object",
            "properties": {
                "twin_employee_id": {"type": "string"},
                "colleague_employee_id": {
                    "type": "string",
                    "description": "Registry id e.g. emp-intern (preferred if known)",
                },
                "colleague_name": {
                    "type": "string",
                    "description": "Display name fragment e.g. intern, Demo Intern",
                },
            },
            "required": ["twin_employee_id"],
        },
        lambda args: _handle_twin_get_colleague_chat(args),
    )


def _handle_jira_create(args: dict[str, Any]) -> dict[str, Any]:
    tools = _tools()
    reporter_id = args.get("reporter_id") or "mcp-client"
    ticket = tools.jira.create_ticket(
        title=args["title"],
        description=args["description"],
        reporter_id=reporter_id,
    )
    return {
        "ticket_id": ticket.ticket_id,
        "title": ticket.title,
        "status": ticket.status.value,
    }


def _handle_jira_get(args: dict[str, Any]) -> dict[str, Any]:
    jira = _tools().jira
    ticket = jira.get_ticket(args["ticket_id"])
    if not ticket:
        raise RuntimeError(f"Ticket not found: {args['ticket_id']}")
    payload: dict[str, Any] = {
        "ticket_id": ticket.ticket_id,
        "title": ticket.title,
        "status": ticket.status.value,
        "assignee_id": ticket.assignee_id,
        "reporter_id": ticket.reporter_id,
        "description": ticket.description or "",
    }
    list_comments = getattr(jira, "list_comments", None)
    if callable(list_comments):
        payload["comments"] = list_comments(ticket.ticket_id)
    else:
        payload["comments"] = []
    return payload


def _handle_jira_list(args: dict[str, Any]) -> list[dict[str, Any]]:
    email = args.get("assignee_email")
    if not email and not is_mock_mode() and is_demo_safe_mode():
        email = jira_email()
    items = _tools().jira.list_tickets(
        assignee_email=email,
        only_demo_tickets=not is_mock_mode(),
    )
    return [
        {
            "ticket_id": i.ticket_id,
            "title": i.title,
            "status": i.status.value,
            "assignee_email": i.assignee_email,
        }
        for i in items
    ]


def _handle_jira_assign(args: dict[str, Any]) -> dict[str, Any]:
    result = _tools().jira.assign_ticket(args["ticket_id"], args["assignee_employee_id"])
    return _result_payload(result)


def _handle_jira_done(args: dict[str, Any]) -> dict[str, Any]:
    result = _tools().jira.update_status(args["ticket_id"], TaskStatus.DONE.value)
    return _result_payload(result)


def _handle_gitlab_list_mrs(args: dict[str, Any]) -> list[dict[str, Any]]:
    gitlab = _tools().gitlab
    list_fn = getattr(gitlab, "list_merge_requests", None)
    if not callable(list_fn):
        raise RuntimeError("GitLab list_merge_requests not available in current toolset")
    state = args.get("state") or "opened"
    limit = int(args.get("limit") or 10)
    mrs = list_fn(state=state, limit=limit)
    return [
        {
            "iid": mr.get("iid"),
            "title": mr.get("title"),
            "web_url": mr.get("web_url"),
            "state": mr.get("state"),
        }
        for mr in mrs
    ]


def _handle_gitlab_link(args: dict[str, Any]) -> dict[str, Any]:
    result = _tools().gitlab.link_mr_to_ticket(args["ticket_id"], args["mr_url"])
    return _result_payload(result)


def _handle_gitlab_create_mr_from_ticket(args: dict[str, Any]) -> dict[str, Any]:
    from agent_network.agent.access_policy import deny_implement_mr_closed_ticket

    ticket_id = str(args["ticket_id"]).strip()
    tools = _tools()
    ticket = tools.jira.get_ticket(ticket_id)
    if not ticket:
        raise RuntimeError(f"Ticket not found: {ticket_id}")
    closed = deny_implement_mr_closed_ticket(ticket.status)
    if closed:
        raise RuntimeError(closed)
    create_fn = getattr(tools.gitlab, "create_mr_from_ticket", None)
    if not callable(create_fn):
        raise RuntimeError("gitlab_create_mr_from_ticket not available in current toolset")
    result = create_fn(
        ticket_id=ticket_id,
        title=ticket.title,
        description=ticket.description or "",
    )
    return _result_payload(result)


def _handle_teams_notify(args: dict[str, Any]) -> dict[str, Any]:
    purpose = (args.get("purpose") or "").strip()
    if is_demo_safe_mode() and not is_mock_mode() and purpose not in (
        "owner_stand_in",
        "ticket_approval_request",
    ):
        return {
            "success": False,
            "detail": "Blocked: JIRA_DEMO_SAFE_MODE=true suppresses Teams notifications",
            "data": {},
        }
    result = _tools().teams.notify_user(args["email"], args["message"])
    return _result_payload(result)


def _handle_workday_manager(args: dict[str, Any]) -> dict[str, Any]:
    result = _tools().workday.get_employee_manager(args["employee_id"])
    emp = employee_by_id(args["employee_id"])
    payload = _result_payload(result)
    if emp:
        payload["employee_name"] = emp.name
    return payload


def _handle_twin_delegate(args: dict[str, Any]) -> dict[str, Any]:
    reporter_id = args.get("reporter_employee_id")
    if not reporter_id:
        raise RuntimeError("reporter_employee_id is required")

    invoker_id = args.get("invoker_employee_id")
    if not invoker_id or invoker_id != reporter_id:
        return _result_payload(
            AgentActionResult(
                success=False,
                detail=(
                    "Only the twin owner can delegate work. "
                    "Colleagues cannot route tasks through this twin."
                ),
            )
        )

    emp = employee_by_id(reporter_id)
    if not emp:
        raise RuntimeError(f"Unknown employee: {reporter_id}")

    # Owner-only tool (invoker must match reporter) — owner authority overrides
    # stand-in policy flags meant for colleague sessions.

    assignee_id = args["assignee_employee_id"]
    _, twins = get_runtime()
    reporter = twins.get(reporter_id)
    if not reporter:
        raise RuntimeError(f"No twin registered for {reporter_id}")

    result = reporter.create_and_delegate_ticket(
        title=args["title"],
        description=args.get("description") or "",
        assignee_employee_id=assignee_id,
    )
    log_twin_action(
        twin_employee_id=reporter_id,
        action="twin_delegate_ticket",
        detail=result.detail,
        data={
            "assignee_employee_id": assignee_id,
            "ticket_id": (result.data or {}).get("ticket_id"),
            "success": result.success,
        },
    )
    payload = _result_payload(result)
    if result.success and result.data:
        payload["ticket_id"] = result.data.get("ticket_id")
        ticket_id = result.data.get("ticket_id")
        policy = get_policy(reporter_id)
        if ticket_id and policy.notify_on_delegate:
            notify_line = notify_twin_owner(
                reporter_id,
                (
                    f"Your twin delegated '{args['title']}' to "
                    f"{employee_display_name(assignee_id)} ({ticket_id}) while you were away."
                ),
            )
            if notify_line:
                payload["owner_notification"] = notify_line
    return payload


def _handle_twin_create_for_requester(args: dict[str, Any]) -> dict[str, Any]:
    from agent_network.absence import is_effectively_absent
    from agent_network.ticket_approval import requires_ticket_approval

    twin_id = args.get("twin_employee_id")
    requester_id = args.get("requester_employee_id")
    if not twin_id or not requester_id:
        raise RuntimeError("twin_employee_id and requester_employee_id are required")

    twin = employee_by_id(twin_id)
    requester = employee_by_id(requester_id)
    if not twin or not requester:
        raise RuntimeError("Unknown twin or requester employee id")

    if requester_id != twin_id and not is_effectively_absent(twin_id):
        return _result_payload(
            AgentActionResult(
                success=False,
                detail=(
                    f"{twin.name} is not marked absent — "
                    "stand-in ticket creation is only available while they are away."
                ),
            )
        )

    policy = get_policy(twin_id)
    if requester_id != twin_id and not policy.can_delegate:
        from agent_network.ticket_approval import requires_ticket_approval

        if not requires_ticket_approval(twin_id):
            return _result_payload(
                AgentActionResult(
                    success=False,
                    detail=(
                        f"{twin.name}'s stand-in policy blocks creating or assigning tickets "
                        "while they are away."
                    ),
                )
            )

    if (
        requester_id != twin_id
        and not args.get("skip_approval")
        and requires_ticket_approval(twin_id)
    ):
        return _result_payload(
            AgentActionResult(
                success=False,
                detail=(
                    "Ticket creation requires owner approval — use the stand-in "
                    "approval queue (colleague session), not direct create."
                ),
            )
        )

    title = str(args.get("title", "")).strip()
    if not title:
        raise RuntimeError("title is required")
    if not title.startswith("["):
        title = f"[Agent-Network-TEST] {title}"

    description = str(args.get("description") or "").strip()
    tools = _tools()
    ticket = tools.jira.create_ticket(
        title=title,
        description=description,
        reporter_id=twin_id,
    )
    assign_result = tools.jira.assign_ticket(ticket.ticket_id, requester_id)
    if not assign_result.success:
        return _result_payload(assign_result)

    log_twin_action(
        twin_employee_id=twin_id,
        action="twin_create_ticket_for_requester",
        detail=f"Created {ticket.ticket_id} for {requester.name}",
        data={
            "ticket_id": ticket.ticket_id,
            "requester_employee_id": requester_id,
            "title": ticket.title,
        },
    )
    return {
        "success": True,
        "ticket_id": ticket.ticket_id,
        "title": ticket.title,
        "assignee_employee_id": requester_id,
        "assignee_name": requester.name,
        "detail": (
            f"Created {ticket.ticket_id} — assigned to {requester.name}."
        ),
    }


def _handle_status() -> dict[str, Any]:
    return {
        "mode": "mock" if is_mock_mode() else "live",
        "demo_safe_mode": is_demo_safe_mode(),
        "jira_email": jira_email() if not is_mock_mode() else None,
        "tools": [t["name"] for t in _TOOLS],
    }


def _handle_twin_get_stand_in_activity(args: dict[str, Any]) -> dict[str, Any]:
    from agent_network import memory
    from agent_network.audit import format_owner_activity_summary

    twin_id = args.get("twin_employee_id")
    if not twin_id:
        raise RuntimeError("twin_employee_id is required")
    colleague_ctx = memory.colleagues_activity_summary(twin_id)
    summary = format_owner_activity_summary(
        twin_id,
        colleague_summary=colleague_ctx,
    )
    return {"summary": summary}


def _handle_twin_get_colleague_chat(args: dict[str, Any]) -> dict[str, Any]:
    from agent_network import memory
    from agent_network.agent.owner_intent import resolve_colleague_requester_from_message
    from agent_network.registry import employee_by_id

    twin_id = args.get("twin_employee_id")
    if not twin_id:
        raise RuntimeError("twin_employee_id is required")

    colleague_id = args.get("colleague_employee_id")
    if colleague_id:
        colleague_id = str(colleague_id).strip()
    else:
        name_hint = str(args.get("colleague_name", "") or "").strip()
        if name_hint:
            colleague_id = resolve_colleague_requester_from_message(name_hint, twin_id)

    if not colleague_id:
        contacts = memory.colleagues_with_conversations(twin_id)
        if not contacts:
            return {
                "transcript": "No colleague stand-in conversations recorded yet.",
                "colleagues": [],
            }
        return {
            "transcript": None,
            "colleagues": [{"employee_id": eid, "name": name} for eid, name in contacts],
            "hint": "Ask owner which colleague — pass colleague_name or colleague_employee_id.",
        }

    emp = employee_by_id(colleague_id)
    transcript = memory.colleague_activity_prompt_block(
        twin_id,
        colleague_requester_id=colleague_id,
        for_owner=True,
    )
    label = emp.name if emp else colleague_id
    return {
        "colleague": label,
        "colleague_employee_id": colleague_id,
        "transcript": transcript or f"No stand-in conversation recorded with {label} yet.",
    }


_register_all()
