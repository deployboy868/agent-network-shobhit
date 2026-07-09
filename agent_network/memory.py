"""
Per-conversation chat memory (SQLite) — verbatim turns.

Derived context summaries live in context_memory.py (same DB file, separate table).
Each chat with a twin has a conversation_id (Teams conversation id, CLI/Streamlit
session key, etc.). We persist turns word-for-word; older turns are folded into
context summaries for long-thread recall.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from agent_network.config import memory_context_turns, memory_db_path, owner_colleague_memory_turns

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_active_path: Optional[str] = None


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            twin_employee_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_conv ON messages(conversation_id, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_twin ON messages(twin_employee_id, id)"
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


def remember(
    conversation_id: str,
    role: str,
    content: str,
    twin_employee_id: Optional[str] = None,
) -> None:
    if not conversation_id or not content:
        return
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO messages (conversation_id, twin_employee_id, role, content, ts) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                twin_employee_id,
                role,
                content,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def recent(conversation_id: str, limit: Optional[int] = None) -> list[dict]:
    """Return recent verbatim chat turns (oldest first) as [{'role','content'}]."""
    if not conversation_id:
        return []
    limit = limit or memory_context_turns()
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def ordered_message_ids(conversation_id: str) -> list[int]:
    """All message ids for a conversation in chronological order."""
    if not conversation_id:
        return []
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return [int(r[0]) for r in rows]


def turns_by_ids(conversation_id: str, message_ids: list[int]) -> list[dict]:
    """Verbatim turns for specific message ids, chronological."""
    if not conversation_id or not message_ids:
        return []
    placeholders = ",".join("?" for _ in message_ids)
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            f"SELECT role, content FROM messages WHERE conversation_id = ? "
            f"AND id IN ({placeholders}) ORDER BY id",
            (conversation_id, *message_ids),
        ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


def history_count(conversation_id: str) -> int:
    if not conversation_id:
        return 0
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def clear(conversation_id: str) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
        )
        conn.commit()
    from agent_network import context_memory

    context_memory.clear(conversation_id)


def clear_all() -> int:
    """Delete every stored chat turn across all conversations."""
    with _lock:
        conn = _get_conn()
        cur = conn.execute("DELETE FROM messages")
        conn.commit()
        count = cur.rowcount
    from agent_network import context_memory

    context_memory.clear_all()
    return count


def owner_coordination_conversation_id(twin_employee_id: str) -> str:
    return f"{twin_employee_id}:{twin_employee_id}"


def list_colleague_conversation_ids(
    twin_employee_id: str,
    *,
    exclude_conversation_id: Optional[str] = None,
) -> list[str]:
    """Conversation ids for this twin excluding the owner coordination thread."""
    if not twin_employee_id:
        return []
    owner_thread = owner_coordination_conversation_id(twin_employee_id)
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT DISTINCT conversation_id FROM messages "
            "WHERE twin_employee_id = ? AND conversation_id != ? "
            "ORDER BY conversation_id",
            (twin_employee_id, owner_thread),
        ).fetchall()
    ids = [r[0] for r in rows]
    if exclude_conversation_id and exclude_conversation_id in ids:
        ids = [c for c in ids if c != exclude_conversation_id]
    return ids


def conversation_id_for_colleague(
    twin_employee_id: str, colleague_requester_id: str
) -> str:
    return f"{twin_employee_id}:{colleague_requester_id}"


def colleagues_with_conversations(twin_employee_id: str) -> list[tuple[str, str]]:
    """Return (requester_employee_id, display_name) for each colleague thread."""
    from agent_network.registry import employee_by_id

    result: list[tuple[str, str]] = []
    for conv_id in list_colleague_conversation_ids(twin_employee_id):
        if ":" not in conv_id:
            continue
        _, requester_id = conv_id.split(":", 1)
        if requester_id == twin_employee_id:
            continue
        emp = employee_by_id(requester_id)
        name = emp.name if emp else requester_id
        result.append((requester_id, name))
    return result


def colleagues_activity_summary(twin_employee_id: str) -> str:
    """Lightweight list of who chatted — no full transcripts."""
    contacts = colleagues_with_conversations(twin_employee_id)
    if not contacts:
        return ""
    names = ", ".join(name for _, name in contacts)
    return f"Colleagues who messaged while you were away: {names}."


def colleague_activity_prompt_block(
    twin_employee_id: str,
    *,
    colleague_requester_id: Optional[str] = None,
    limit_per_conversation: Optional[int] = None,
    for_owner: bool = True,
) -> str:
    """
    Formatted transcript for one colleague's stand-in chat (or all if no filter).

    Caller must enforce for_owner — only the twin owner may receive this data.
    Prefer colleague_requester_id to load a single conversation only.
    """
    if not for_owner or not twin_employee_id:
        return ""
    from agent_network.registry import employee_by_id

    if colleague_requester_id:
        conv_ids = [
            conversation_id_for_colleague(twin_employee_id, colleague_requester_id)
        ]
        from agent_network import context_memory

        if not recent(conv_ids[0], limit=1) and not context_memory.get_summary(
            conv_ids[0]
        ):
            emp = employee_by_id(colleague_requester_id)
            label = emp.name if emp else colleague_requester_id
            return f"No stand-in conversation recorded with {label} yet."
    else:
        conv_ids = list_colleague_conversation_ids(twin_employee_id)
        if not conv_ids:
            return ""

    per_conv = limit_per_conversation or owner_colleague_memory_turns()
    lines: list[str] = []

    from agent_network import context_memory

    for conv_id in conv_ids:
        turns = recent(conv_id, limit=per_conv)
        ctx = context_memory.get_summary(conv_id)
        if not turns and not ctx:
            continue
        label = _conversation_label(conv_id, twin_employee_id, employee_by_id)
        if for_owner and len(conv_ids) == 1:
            lines.append(f"Recent chat with {label}:")
        elif for_owner:
            lines.append(f"\nWith {label}:")
        else:
            lines.append(f"\n--- With {label} ---")
        if ctx:
            lines.append(f"Context (derived): {ctx.replace(chr(10), ' ').strip()}")
        for turn in turns:
            role = turn["role"]
            who = label if role == "user" else "Twin"
            content = turn["content"].replace("\n", " ").strip()
            if len(content) > 500:
                content = content[:497] + "..."
            lines.append(f"{who}: {content}")

    if not lines:
        return ""
    return "\n".join(lines)


def _conversation_label(conv_id: str, twin_id: str, employee_lookup) -> str:
    if ":" in conv_id:
        _, requester_id = conv_id.split(":", 1)
        if requester_id == twin_id:
            return "owner"
        emp = employee_lookup(requester_id)
        if emp:
            return emp.name
        return requester_id
    return conv_id[:48]


def reset_memory() -> None:
    """Close and forget the connection (tests)."""
    global _conn, _active_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _active_path = None
    from agent_network import context_memory

    context_memory.reset_context_memory()
