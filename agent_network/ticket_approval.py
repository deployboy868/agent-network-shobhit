"""
Pending ticket approvals — proactive owner notify + confirm before create.

When the owner sets a rule like "notify and confirm before creating tickets",
colleague ticket requests are queued, the owner is pinged on Teams, and the ticket
is only created after the owner approves (e.g. "approve TA-1").
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from agent_network.config import memory_db_path
from agent_network.registry import employee_display_name

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_active_path: Optional[str] = None

_STATUS_PENDING = "pending"
_STATUS_APPROVED = "approved"
_STATUS_REJECTED = "rejected"

_TICKET_CUES = (
    "ticket",
    "create a ticket",
    "file a ticket",
    "jira",
)
_APPROVAL_CUES = (
    "confirm",
    "confirmation",
    "approval",
    "approve",
    "notify me",
    "notify and",
    "notify whenever",
    "text me",
    "message me",
    "ping me",
    "check with me",
    "ask me",
    "check with",
    "put on hold",
    "put them on hold",
    "on hold",
    "before creating",
    "before you create",
    "without my",
    "until i approve",
    "need my ok",
    "need my approval",
    "whenever someone asks",
    "when someone asks",
    "if someone asks",
)

_REF_RE = re.compile(r"\bTA-(\d+)\b", re.IGNORECASE)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_ticket_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_code TEXT NOT NULL UNIQUE,
            twin_employee_id TEXT NOT NULL,
            requester_employee_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            ticket_id TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pta_twin_status "
        "ON pending_ticket_approvals (twin_employee_id, status, id)"
    )
    conn.commit()
    return conn


def _get_conn() -> sqlite3.Connection:
    global _conn, _active_path
    path = memory_db_path()
    if _conn is None or _active_path != path:
        _conn = _connect(path)
        _active_path = path
    return _conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def wants_ticket_hold_and_notify(text: str) -> bool:
    """Owner wants hold + proactive notify on colleague ticket asks (no 'ticket' word required)."""
    lower = (text or "").lower()
    if not lower.strip():
        return False
    asks_pattern = any(
        p in lower
        for p in (
            "someone asks",
            "anyone asks",
            "they ask",
            "asks to make",
            "asks for a ticket",
            "asks you to make",
            "ask you to make",
            "make a ticket",
        )
    )
    notify_pattern = any(
        p in lower
        for p in ("text me", "notify me", "message me", "ping me", "confirm with me")
    )
    hold_pattern = "hold" in lower
    return (asks_pattern and notify_pattern) or (asks_pattern and hold_pattern)


def rule_requires_ticket_approval(text: str) -> bool:
    """Heuristic: owner rule text implies confirm-before-create for tickets."""
    if wants_ticket_hold_and_notify(text):
        return True
    lower = (text or "").lower()
    if not lower.strip():
        return False
    has_ticket = any(cue in lower for cue in _TICKET_CUES)
    has_approval = any(cue in lower for cue in _APPROVAL_CUES)
    return has_ticket and has_approval


def requires_ticket_approval(twin_employee_id: str) -> bool:
    """True when owner policy or active rules require approval before ticket create."""
    from agent_network import owner_instruction_memory
    from agent_network.standin_policy import get_policy

    policy = get_policy(twin_employee_id)
    if policy.require_ticket_approval:
        return True
    if policy.instructions and rule_requires_ticket_approval(policy.instructions):
        return True
    for rule in owner_instruction_memory.list_active_rules(twin_employee_id):
        if rule_requires_ticket_approval(rule.get("rule_text", "")):
            return True
    return False


def sync_ticket_approval_policy(twin_employee_id: str) -> bool:
    """
    Flip require_ticket_approval on stand-in policy from owner rules/instructions.
    Returns True if the flag changed.
    """
    from agent_network.agent.owner_rule_classifier import derive_policy_from_rules
    from agent_network.standin_policy import get_policy

    before = get_policy(twin_employee_id).require_ticket_approval
    derive_policy_from_rules(twin_employee_id)
    after = get_policy(twin_employee_id).require_ticket_approval
    return before != after


def apply_ticket_approval_flag_from_text(twin_employee_id: str, text: str) -> bool:
    """Set require_ticket_approval when owner message implies it."""
    from agent_network.standin_policy import get_policy, set_policy

    if not rule_requires_ticket_approval(text) and not wants_ticket_hold_and_notify(text):
        return False
    policy = get_policy(twin_employee_id)
    if policy.require_ticket_approval:
        return False
    policy.require_ticket_approval = True
    set_policy(twin_employee_id, policy)
    return True


def _row_to_dict(row: tuple) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "ref_code": row[1],
        "twin_employee_id": row[2],
        "requester_employee_id": row[3],
        "conversation_id": row[4],
        "title": row[5],
        "description": row[6] or "",
        "status": row[7],
        "ticket_id": row[8],
        "created_at": row[9],
        "resolved_at": row[10],
    }


def _ref_code(row_id: int) -> str:
    return f"TA-{row_id}"


def get_pending(ref_code: str, twin_employee_id: str = "") -> Optional[dict[str, Any]]:
    code = (ref_code or "").strip().upper()
    if not code:
        return None
    with _lock:
        conn = _get_conn()
        if twin_employee_id:
            row = conn.execute(
                "SELECT id, ref_code, twin_employee_id, requester_employee_id, "
                "conversation_id, title, description, status, ticket_id, "
                "created_at, resolved_at "
                "FROM pending_ticket_approvals WHERE ref_code = ? AND twin_employee_id = ?",
                (code, twin_employee_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, ref_code, twin_employee_id, requester_employee_id, "
                "conversation_id, title, description, status, ticket_id, "
                "created_at, resolved_at "
                "FROM pending_ticket_approvals WHERE ref_code = ?",
                (code,),
            ).fetchone()
    return _row_to_dict(row) if row else None


def list_pending(twin_employee_id: str) -> list[dict[str, Any]]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, ref_code, twin_employee_id, requester_employee_id, "
            "conversation_id, title, description, status, ticket_id, "
            "created_at, resolved_at "
            "FROM pending_ticket_approvals "
            "WHERE twin_employee_id = ? AND status = ? ORDER BY id",
            (twin_employee_id, _STATUS_PENDING),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def find_open_for_requester(
    twin_employee_id: str, requester_employee_id: str, title: str = ""
) -> Optional[dict[str, Any]]:
    """Return a pending or recently approved request matching the colleague."""
    title_norm = (title or "").strip().lower()
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, ref_code, twin_employee_id, requester_employee_id, "
            "conversation_id, title, description, status, ticket_id, "
            "created_at, resolved_at "
            "FROM pending_ticket_approvals "
            "WHERE twin_employee_id = ? AND requester_employee_id = ? "
            "AND status IN (?, ?) ORDER BY id DESC LIMIT 5",
            (twin_employee_id, requester_employee_id, _STATUS_PENDING, _STATUS_APPROVED),
        ).fetchall()
    for row in rows:
        item = _row_to_dict(row)
        if not title_norm or item["title"].lower() == title_norm:
            return item
    return _row_to_dict(rows[0]) if rows else None


def owner_session_conversation_id(twin_employee_id: str) -> str:
    """Conversation id when the twin owner talks to their own twin."""
    return f"{twin_employee_id}:{twin_employee_id}"


def format_owner_proactive_alert(
    requester_name: str, title: str, ref_code: str
) -> str:
    return (
        f"**Proactive alert** — while you were away, **{requester_name}** asked me to "
        f"create a ticket: **{title}**.\n\n"
        f"I've put them on hold and notified you on Teams. "
        f"Reference: **{ref_code}**.\n\n"
        f"Reply **approve {ref_code}** to create the ticket, or **reject {ref_code}** to decline."
    )


def _owner_chat_already_has_ref(twin_employee_id: str, ref_code: str) -> bool:
    from agent_network import memory

    conv = owner_session_conversation_id(twin_employee_id)
    for turn in memory.recent(conv, limit=40):
        if turn.get("role") == "assistant" and ref_code in turn.get("content", ""):
            return True
    return False


def post_owner_chat_alert(twin_employee_id: str, message: str, *, ref_code: str = "") -> bool:
    """
    Push a proactive assistant message into the owner's chat thread with their twin.
    Returns True if a new message was written.
    """
    from agent_network import memory

    text = (message or "").strip()
    if not twin_employee_id or not text:
        return False
    if ref_code and _owner_chat_already_has_ref(twin_employee_id, ref_code):
        return False
    conv = owner_session_conversation_id(twin_employee_id)
    memory.remember(conv, "assistant", text, twin_employee_id)
    return True


def post_owner_approval_resolved(
    twin_employee_id: str,
    *,
    ref_code: str,
    approved: bool,
    requester_name: str,
    title: str,
    ticket_id: str = "",
) -> None:
    """Record approve/reject outcome in the owner's chat thread."""
    if approved and ticket_id:
        text = (
            f"**{ref_code} approved** — I created **{ticket_id}** for {requester_name}: "
            f"{title}."
        )
    elif approved:
        text = f"**{ref_code} approved** for {requester_name}: {title}."
    else:
        text = (
            f"**{ref_code} declined** — I won't create a ticket for {requester_name}: "
            f"{title}."
        )
    post_owner_chat_alert(twin_employee_id, text, ref_code=f"{ref_code}-resolved")


def queue_ticket_approval_request(
    *,
    twin_employee_id: str,
    requester_employee_id: str,
    conversation_id: str,
    title: str,
    description: str = "",
) -> dict[str, Any]:
    """Create a pending approval and proactively notify the twin owner."""
    from agent_network.audit import log_twin_action
    from agent_network.notify import notify_owner_ticket_approval_request

    ts = _now()
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO pending_ticket_approvals "
            "(ref_code, twin_employee_id, requester_employee_id, conversation_id, "
            "title, description, status, created_at) "
            "VALUES ('', ?, ?, ?, ?, ?, ?, ?)",
            (
                twin_employee_id,
                requester_employee_id,
                conversation_id,
                title.strip(),
                (description or "").strip(),
                _STATUS_PENDING,
                ts,
            ),
        )
        row_id = int(cur.lastrowid)
        ref = _ref_code(row_id)
        conn.execute(
            "UPDATE pending_ticket_approvals SET ref_code = ? WHERE id = ?",
            (ref, row_id),
        )
        conn.commit()

    requester_name = employee_display_name(requester_employee_id)
    notify_line = notify_owner_ticket_approval_request(
        twin_employee_id,
        (
            f"{requester_name} asked your twin to create a ticket: "
            f"\"{title.strip()}\" ({ref}). "
            f"Reply to your twin: approve {ref} — or reject {ref}."
        ),
        ref_code=ref,
    )

    log_twin_action(
        twin_employee_id=twin_employee_id,
        action="ticket_approval_queued",
        detail=f"Queued {ref} for {requester_name}: {title.strip()}",
        data={
            "ref_code": ref,
            "requester_employee_id": requester_employee_id,
            "title": title.strip(),
            "owner_notified": bool(notify_line),
        },
    )

    chat_alert = format_owner_proactive_alert(requester_name, title.strip(), ref)
    post_owner_chat_alert(twin_employee_id, chat_alert, ref_code=ref)

    pending = get_pending(ref, twin_employee_id)
    assert pending is not None
    pending["owner_notification"] = notify_line
    return pending


def approve_pending(ref_code: str, twin_employee_id: str) -> dict[str, Any]:
    """Owner approved — create the Jira ticket for the requester."""
    from agent_network.audit import log_twin_action
    from agent_network.mcp_server.tools_registry import call_tool

    pending = get_pending(ref_code, twin_employee_id)
    if not pending:
        return {"success": False, "detail": f"No pending request {ref_code}."}
    if pending["status"] != _STATUS_PENDING:
        if pending["status"] == _STATUS_APPROVED and pending.get("ticket_id"):
            return {
                "success": True,
                "detail": f"Already approved — ticket {pending['ticket_id']}.",
                "ticket_id": pending["ticket_id"],
                "ref_code": ref_code,
            }
        return {
            "success": False,
            "detail": f"{ref_code} was already {pending['status']}.",
        }

    result = call_tool(
        "twin_create_ticket_for_requester",
        {
            "twin_employee_id": twin_employee_id,
            "requester_employee_id": pending["requester_employee_id"],
            "title": pending["title"],
            "description": pending["description"],
            "skip_approval": True,
        },
    )
    if result.get("isError"):
        return {"success": False, "detail": result["content"][0]["text"]}

    data = json.loads(result["content"][0]["text"])
    ticket_id = data.get("ticket_id", "")
    ts = _now()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE pending_ticket_approvals "
            "SET status = ?, ticket_id = ?, resolved_at = ? WHERE ref_code = ?",
            (_STATUS_APPROVED, ticket_id, ts, ref_code.upper()),
        )
        conn.commit()

    requester_name = employee_display_name(pending["requester_employee_id"])
    log_twin_action(
        twin_employee_id=twin_employee_id,
        action="ticket_approval_granted",
        detail=f"Approved {ref_code} → {ticket_id} for {requester_name}",
        data={
            "ref_code": ref_code,
            "ticket_id": ticket_id,
            "requester_employee_id": pending["requester_employee_id"],
            "title": pending["title"],
        },
    )
    return {
        "success": True,
        "detail": f"Created {ticket_id} for {requester_name}.",
        "ticket_id": ticket_id,
        "ref_code": ref_code,
        "requester_name": requester_name,
        "title": pending["title"],
    }


def reject_pending(ref_code: str, twin_employee_id: str) -> dict[str, Any]:
    """Owner declined the ticket request."""
    from agent_network.audit import log_twin_action

    pending = get_pending(ref_code, twin_employee_id)
    if not pending:
        return {"success": False, "detail": f"No pending request {ref_code}."}
    if pending["status"] != _STATUS_PENDING:
        return {
            "success": False,
            "detail": f"{ref_code} was already {pending['status']}.",
        }

    ts = _now()
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE pending_ticket_approvals SET status = ?, resolved_at = ? "
            "WHERE ref_code = ?",
            (_STATUS_REJECTED, ts, ref_code.upper()),
        )
        conn.commit()

    requester_name = employee_display_name(pending["requester_employee_id"])
    log_twin_action(
        twin_employee_id=twin_employee_id,
        action="ticket_approval_rejected",
        detail=f"Rejected {ref_code} for {requester_name}: {pending['title']}",
        data={
            "ref_code": ref_code,
            "requester_employee_id": pending["requester_employee_id"],
            "title": pending["title"],
        },
    )
    return {
        "success": True,
        "detail": f"Declined {ref_code} — won't create a ticket for {requester_name}.",
        "ref_code": ref_code,
        "requester_name": requester_name,
        "title": pending["title"],
    }


def parse_owner_approval_message(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse owner approve/reject commands.
    Returns (action, ref_code) where action is 'approve' | 'reject' | None.
    """
    lower = (text or "").lower().strip()
    if not lower:
        return None, None

    m = _REF_RE.search(text)
    ref = m.group(0).upper() if m else None

    reject_cues = (
        "reject ",
        "deny ",
        "decline ",
        "don't create",
        "do not create",
        "dont create",
        "no ticket",
    )
    approve_cues = (
        "approve ",
        "go ahead",
        "yes create",
        "yes, create",
        "create it",
        "ok create",
        "okay create",
        "sounds good",
    )

    if any(lower.startswith(c) or f" {c}" in lower for c in reject_cues):
        return "reject", ref
    if any(c in lower for c in approve_cues):
        return "approve", ref
    if lower in {"approve", "yes", "go ahead", "create it", "ok", "okay"}:
        return "approve", ref
    return None, None


def format_pending_list(twin_employee_id: str) -> str:
    pending = list_pending(twin_employee_id)
    if not pending:
        return "No pending ticket approvals."
    lines = ["Pending ticket approvals:"]
    for item in pending:
        who = employee_display_name(item["requester_employee_id"])
        lines.append(f"  • {item['ref_code']}: {who} — \"{item['title']}\"")
    lines.append("Reply e.g. approve TA-1 or reject TA-1.")
    return "\n".join(lines)


def colleague_pending_message(
    *,
    twin_employee_id: str,
    requester_employee_id: str,
    conversation_id: str,
    title: str,
    owner_name: str,
) -> str:
    """User-facing reply when a ticket request is queued for owner approval."""
    existing = find_open_for_requester(twin_employee_id, requester_employee_id, title)
    if existing:
        if existing["status"] == _STATUS_PENDING:
            ref = existing["ref_code"]
            return (
                f"I already sent that to {owner_name} for approval (**{ref}**). "
                "I'm waiting on their OK before I create the ticket."
            )
        if existing["status"] == _STATUS_APPROVED and existing.get("ticket_id"):
            tid = existing["ticket_id"]
            return (
                f"Good news — {owner_name} approved your request. "
                f"Ticket **{tid}** is on your board: {existing['title']}."
            )

    pending = queue_ticket_approval_request(
        twin_employee_id=twin_employee_id,
        requester_employee_id=requester_employee_id,
        conversation_id=conversation_id,
        title=title,
    )
    ref = pending["ref_code"]
    notify_bit = ""
    if pending.get("owner_notification"):
        notify_bit = f" {pending['owner_notification']}"
    elif pending.get("owner_notification") is None:
        pass
    return (
        f"{owner_name} asked me to check with them before creating tickets. "
        f"I've **notified them** and queued your request (**{ref}**). "
        f"I'll create the ticket once they approve — ask me again in a bit if you like."
        f"{notify_bit}"
    )


def clear_all() -> int:
    with _lock:
        conn = _get_conn()
        cur = conn.execute("DELETE FROM pending_ticket_approvals")
        conn.commit()
        return cur.rowcount


def reset_ticket_approval_memory() -> None:
    global _conn, _active_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _active_path = None
