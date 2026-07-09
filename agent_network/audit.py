"""Append-only audit log for twin actions."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_LOG = _PROJECT_ROOT / ".twin-audit.jsonl"


def log_twin_action(
    *,
    twin_employee_id: str,
    action: str,
    detail: str,
    data: dict[str, Any] | None = None,
    log_path: Path | None = None,
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "twin_employee_id": twin_employee_id,
        "action": action,
        "detail": detail,
        "data": data or {},
    }
    path = log_path or Path(os.getenv("TWIN_AUDIT_LOG", str(_DEFAULT_LOG)))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_twin_audit(
    twin_employee_id: str,
    *,
    limit: int = 20,
    log_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return recent audit entries for one twin (newest last)."""
    path = log_path or Path(os.getenv("TWIN_AUDIT_LOG", str(_DEFAULT_LOG)))
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("twin_employee_id") == twin_employee_id:
                entries.append(entry)
    return entries[-limit:]


_CREATE_TICKET = "twin_create_ticket_for_requester"
_DELEGATE_TICKET = "twin_delegate_ticket"
_APPROVAL_QUEUED = "ticket_approval_queued"
_APPROVAL_GRANTED = "ticket_approval_granted"
_APPROVAL_REJECTED = "ticket_approval_rejected"
_TICKET_ACTIONS = frozenset({_CREATE_TICKET, _DELEGATE_TICKET})
_APPROVAL_ACTIONS = frozenset(
    {_APPROVAL_QUEUED, _APPROVAL_GRANTED, _APPROVAL_REJECTED}
)


def format_owner_activity_summary(
    twin_employee_id: str,
    *,
    limit: int = 30,
    colleague_summary: str = "",
    log_path: Path | None = None,
) -> str:
    """
    Human-readable stand-in activity for the owner — built from audit facts only.
    """
    from agent_network.registry import employee_display_name

    entries = read_twin_audit(twin_employee_id, limit=limit, log_path=log_path)
    created = [e for e in entries if e.get("action") == _CREATE_TICKET]
    delegated = [e for e in entries if e.get("action") == _DELEGATE_TICKET]
    queued = [e for e in entries if e.get("action") == _APPROVAL_QUEUED]
    other = [
        e
        for e in entries
        if e.get("action") not in _TICKET_ACTIONS
        and e.get("action") not in _APPROVAL_ACTIONS
    ]

    lines: list[str] = ["While you were away, here's what I did:"]

    if queued:
        lines.append(f"\nTicket requests waiting for your approval ({len(queued)}):")
        for e in queued[-8:]:
            data = e.get("data") or {}
            ref = data.get("ref_code", "?")
            requester_id = data.get("requester_employee_id", "")
            who = (
                employee_display_name(requester_id)
                if requester_id
                else "colleague"
            )
            title = data.get("title", "")
            title_bit = f" — {title}" if title else ""
            notified = " (you were notified on Teams)" if data.get("owner_notified") else ""
            lines.append(f"  • {ref} from {who}{title_bit}{notified}")
    else:
        lines.append("\nTicket requests waiting for your approval: none.")

    try:
        from agent_network.ticket_approval import list_pending

        still_pending = list_pending(twin_employee_id)
        if still_pending:
            lines.append("\nStill pending (reply approve TA-X):")
            for item in still_pending:
                who = employee_display_name(item["requester_employee_id"])
                lines.append(f"  • {item['ref_code']}: {who} — \"{item['title']}\"")
    except Exception:
        pass

    if created:
        lines.append(f"\nTickets created for colleagues ({len(created)}):")
        for e in created[-8:]:
            data = e.get("data") or {}
            tid = data.get("ticket_id", "?")
            requester_id = data.get("requester_employee_id", "")
            who = (
                employee_display_name(requester_id)
                if requester_id
                else e.get("detail", "")
            )
            title = data.get("title", "")
            title_bit = f" — {title}" if title else ""
            lines.append(f"  • {tid} for {who}{title_bit}")
    else:
        lines.append("\nTickets created for colleagues: none.")

    if delegated:
        lines.append(f"\nTickets delegated to others ({len(delegated)}):")
        for e in delegated[-8:]:
            data = e.get("data") or {}
            tid = data.get("ticket_id", "?")
            assignee_id = data.get("assignee_employee_id", "")
            who = employee_display_name(assignee_id) if assignee_id else "assignee"
            lines.append(f"  • {tid} → {who}")
    else:
        lines.append("\nTickets delegated to others: none.")

    if other:
        lines.append("\nOther stand-in actions:")
        for e in other[-8:]:
            ts = e.get("ts", "")[:16].replace("T", " ")
            lines.append(f"  • [{ts}] {e.get('detail', e.get('action', ''))}")

    if colleague_summary:
        lines.append(f"\n{colleague_summary}")

    if not entries and not colleague_summary:
        return "No twin activity or colleague conversations recorded yet."
    return "\n".join(lines)


def format_owner_ticket_assignment_summary(
    twin_employee_id: str,
    *,
    limit: int = 30,
    log_path: Path | None = None,
) -> str:
    """Owner asked specifically about assigning/creating tickets for others."""
    from agent_network.registry import employee_display_name

    entries = read_twin_audit(twin_employee_id, limit=limit, log_path=log_path)
    ticket_events = [e for e in entries if e.get("action") in _TICKET_ACTIONS]
    if not ticket_events:
        return (
            "No — I haven't created or delegated any tickets while you've been away "
            "(per stand-in audit log)."
        )
    created = [e for e in ticket_events if e.get("action") == _CREATE_TICKET]
    delegated = [e for e in ticket_events if e.get("action") == _DELEGATE_TICKET]
    lines: list[str] = []
    if created or delegated:
        parts: list[str] = []
        if created:
            parts.append(f"created {len(created)} ticket(s) for colleagues")
        if delegated:
            parts.append(f"delegated {len(delegated)} ticket(s)")
        lines.append(f"Yes — I {' and '.join(parts)} while you were away:")
    for e in ticket_events[-8:]:
        data = e.get("data") or {}
        tid = data.get("ticket_id", "?")
        if e.get("action") == _CREATE_TICKET:
            rid = data.get("requester_employee_id", "")
            who = employee_display_name(rid) if rid else "colleague"
            lines.append(f"  • Created {tid} for {who}")
        else:
            aid = data.get("assignee_employee_id", "")
            who = employee_display_name(aid) if aid else "assignee"
            lines.append(f"  • Delegated {tid} to {who}")
    return "\n".join(lines)


def clear_audit_log(log_path: Path | None = None) -> int:
    """Truncate audit log. Returns number of entries removed."""
    path = log_path or Path(os.getenv("TWIN_AUDIT_LOG", str(_DEFAULT_LOG)))
    removed = 0
    if path.exists():
        with path.open(encoding="utf-8") as f:
            removed = sum(1 for line in f if line.strip())
        path.write_text("")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return removed
