"""
Persistent memory of what each twin's owner told them.

Unlike per-conversation chat memory (SQLite messages by conversation_id), owner
briefings are keyed by twin_employee_id and injected into EVERY session — owner
coordination chats and colleague stand-in chats alike.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from agent_network.config import memory_db_path, owner_memory_turns

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_active_path: Optional[str] = None


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_briefings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            twin_employee_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_owner_twin ON owner_briefings (twin_employee_id, id)"
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


def should_persist_owner_briefing(user_message: str) -> bool:
    """Skip noise / read-only queries — keep everything else the owner says."""
    from agent_network.agent.conversational import is_explicit_help_request
    from agent_network.agent.owner_intent import (
        is_delegate_activity_query,
        is_owner_activity_query,
    )

    text = (user_message or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower in {"help", "?", "commands"}:
        return False
    if is_explicit_help_request(text):
        return False
    if is_owner_activity_query(lower) or is_delegate_activity_query(lower):
        return False
    if any(
        p in lower
        for p in (
            "stand-in settings",
            "stand in settings",
            "show stand-in",
            "stand-in policy",
            "stand in policy",
        )
    ):
        return False
    return True


def remember(
    twin_employee_id: str,
    role: str,
    content: str,
) -> None:
    if not twin_employee_id or not content or not content.strip():
        return
    if role not in ("user", "assistant"):
        return
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO owner_briefings (twin_employee_id, role, content, ts) "
            "VALUES (?, ?, ?, ?)",
            (
                twin_employee_id,
                role,
                content.strip(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def record_owner_exchange(
    twin_employee_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """Save an owner↔twin turn pair when the owner is briefing their twin."""
    if not should_persist_owner_briefing(user_message):
        return
    from agent_network.agent.owner_intent import apply_stand_in_flags_from_owner_text

    apply_stand_in_flags_from_owner_text(twin_employee_id, user_message)
    remember(twin_employee_id, "user", user_message)
    reply = (assistant_reply or "").strip()
    if reply and len(reply) > 3:
        remember(twin_employee_id, "assistant", reply)


def recent(twin_employee_id: str, limit: Optional[int] = None) -> list[dict]:
    if not twin_employee_id:
        return []
    limit = limit or owner_memory_turns()
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT role, content FROM owner_briefings "
            "WHERE twin_employee_id = ? ORDER BY id DESC LIMIT ?",
            (twin_employee_id, limit),
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def count(twin_employee_id: str) -> int:
    if not twin_employee_id:
        return 0
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM owner_briefings WHERE twin_employee_id = ?",
            (twin_employee_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def clear(twin_employee_id: str) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "DELETE FROM owner_briefings WHERE twin_employee_id = ?",
            (twin_employee_id,),
        )
        conn.commit()


def clear_all() -> int:
    """Delete every owner briefing across all twins."""
    with _lock:
        conn = _get_conn()
        cur = conn.execute("DELETE FROM owner_briefings")
        conn.commit()
        return cur.rowcount


def reset_owner_memory() -> None:
    global _conn, _active_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _active_path = None


def prompt_block(twin_employee_id: str, owner_name: str) -> str:
    """
    Text injected into system prompts so the twin follows owner briefings
    when talking to anyone.
    """
    from agent_network.registry import employee_by_id
    from agent_network.standin_policy import get_policy

    turns = recent(twin_employee_id)
    policy = get_policy(twin_employee_id)
    policy_text = (policy.instructions or "").strip()

    if not turns and not policy_text:
        return ""

    lines = [
        f"What {owner_name} has told you — apply in EVERY conversation "
        f"(with {owner_name} and with colleagues). Reason from this; do not ignore it:",
    ]

    owner = employee_by_id(twin_employee_id)
    owner_label = owner.name if owner else owner_name

    for turn in turns:
        label = owner_label if turn["role"] == "user" else "Twin acknowledged"
        content = turn["content"].replace("\n", " ").strip()
        if len(content) > 600:
            content = content[:597] + "..."
        lines.append(f"  • {label}: {content}")

    if policy_text and not _policy_already_in_turns(turns, policy_text):
        lines.append(f"  • {owner_label} (standing rules): {policy_text}")

    lines.append(
        "When a colleague (e.g. an intern) asks for help, follow these guardrails — "
        "tone, what to offer, what to avoid, and how to handle specific topics."
    )
    return "\n".join(lines)


def _policy_already_in_turns(turns: list[dict], policy_text: str) -> bool:
    needle = policy_text.lower().strip()
    if not needle:
        return True
    for turn in turns:
        if needle in turn.get("content", "").lower():
            return True
    return False
