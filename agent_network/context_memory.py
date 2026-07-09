"""
Derived conversation context — separate from verbatim chat memory.

Chat turns live in memory.messages (word-for-word). This module folds older turns
into a compact summary so long threads retain ticket IDs, decisions, and blockers
without sending the full transcript to the LLM.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

from agent_network.config import (
    context_recent_verbatim_turns,
    context_summary_max_chars,
    is_llm_enabled,
    memory_db_path,
)

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_active_path: Optional[str] = None

_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-[A-Z0-9]+)\b", re.IGNORECASE)
_MR_URL_RE = re.compile(r"https?://\S+")


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_context (
            conversation_id TEXT PRIMARY KEY,
            twin_employee_id TEXT,
            summary TEXT NOT NULL,
            through_message_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ctx_twin ON conversation_context (twin_employee_id)"
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


def _record(
    conversation_id: str,
    twin_employee_id: Optional[str],
    summary: str,
    through_message_id: int,
) -> None:
    cap = context_summary_max_chars()
    text = (summary or "").strip()
    if len(text) > cap:
        text = text[: cap - 3] + "..."
    with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT INTO conversation_context
                (conversation_id, twin_employee_id, summary, through_message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                twin_employee_id = excluded.twin_employee_id,
                summary = excluded.summary,
                through_message_id = excluded.through_message_id,
                updated_at = excluded.updated_at
            """,
            (
                conversation_id,
                twin_employee_id,
                text,
                through_message_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_summary(conversation_id: str) -> Optional[str]:
    if not conversation_id:
        return None
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT summary FROM conversation_context WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    if not row:
        return None
    text = (row[0] or "").strip()
    return text or None


def through_message_id(conversation_id: str) -> int:
    if not conversation_id:
        return 0
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT through_message_id FROM conversation_context WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def clear(conversation_id: str) -> None:
    if not conversation_id:
        return
    with _lock:
        conn = _get_conn()
        conn.execute(
            "DELETE FROM conversation_context WHERE conversation_id = ?",
            (conversation_id,),
        )
        conn.commit()


def clear_all() -> int:
    with _lock:
        conn = _get_conn()
        cur = conn.execute("DELETE FROM conversation_context")
        conn.commit()
        return cur.rowcount


def reset_context_memory() -> None:
    global _conn, _active_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _active_path = None


def prompt_block(conversation_id: str) -> str:
    """Text injected into LLM system prompts for this thread."""
    summary = get_summary(conversation_id)
    if not summary:
        return ""
    return (
        "Earlier in this conversation (derived context — not verbatim chat):\n"
        f"{summary}"
    )


def _format_turns_for_summary(turns: list[dict]) -> str:
    lines: list[str] = []
    for turn in turns:
        role = turn.get("role", "user")
        who = "User" if role == "user" else "Twin"
        content = (turn.get("content") or "").replace("\n", " ").strip()
        if len(content) > 800:
            content = content[:797] + "..."
        lines.append(f"{who}: {content}")
    return "\n".join(lines)


def _deterministic_summary(
    previous: str,
    turns: list[dict],
) -> str:
    bullets: list[str] = []
    seen: set[str] = set()

    def add(line: str) -> None:
        key = line.lower().strip()
        if not key or key in seen:
            return
        seen.add(key)
        bullets.append(line)

    if previous:
        for line in previous.splitlines():
            stripped = line.strip().lstrip("•-* ").strip()
            if stripped:
                add(stripped)

    tickets: list[str] = []
    for turn in turns:
        text = turn.get("content") or ""
        for tid in _TICKET_RE.findall(text):
            up = tid.upper()
            if up not in tickets:
                tickets.append(up)
        for url in _MR_URL_RE.findall(text):
            add(f"MR/link mentioned: {url[:120]}")

    if tickets:
        add(f"Tickets discussed: {', '.join(tickets)}")

    for turn in turns:
        role = turn.get("role", "user")
        text = (turn.get("content") or "").strip()
        if not text:
            continue
        first = text.split("\n", 1)[0].strip()
        if len(first) > 160:
            first = first[:157] + "..."
        label = "User asked" if role == "user" else "Twin replied"
        add(f"{label}: {first}")

    if not bullets:
        return previous or ""
    return "\n".join(f"• {b}" for b in bullets)


def _llm_summary(previous: str, turns: list[dict]) -> Optional[str]:
    if not is_llm_enabled():
        return None
    try:
        from agent_network.agent.llm_router import _make_client, _model_name

        client = _make_client()
        model = _model_name()
        transcript = _format_turns_for_summary(turns)
        user_parts = [
            "Update the conversation context summary.",
            "Keep durable facts only: ticket IDs, blockers, decisions, commitments, "
            "delegations, MR links, and open questions.",
            "Do NOT quote messages verbatim. Use short bullet points.",
            f"Max {context_summary_max_chars()} characters total.",
        ]
        if previous:
            user_parts.append(f"\nExisting context:\n{previous}")
        user_parts.append(f"\nNew turns to fold in:\n{transcript}")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You compress twin chat history into a durable context summary "
                        "for later recall. Output bullet points only, no preamble."
                    ),
                },
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            temperature=0.2,
        )
        content = (response.choices[0].message.content or "").strip()
        return content or None
    except Exception as e:
        logger.debug("context LLM summary failed: %s", e)
        return None


def _merge_summary(previous: str, turns: list[dict]) -> str:
    llm = _llm_summary(previous, turns)
    if llm:
        return llm
    return _deterministic_summary(previous, turns)


def refresh_from_chat(
    conversation_id: str,
    twin_employee_id: Optional[str] = None,
) -> bool:
    """
    Fold chat turns that fell outside the verbatim window into derived context.

    Returns True when the stored summary was updated.
    """
    if not conversation_id:
        return False

    from agent_network import memory

    keep = context_recent_verbatim_turns()
    ordered = memory.ordered_message_ids(conversation_id)
    if len(ordered) <= keep:
        return False

    recent_floor = ordered[-keep]
    through = through_message_id(conversation_id)
    to_fold = [mid for mid in ordered if through < mid < recent_floor]
    if not to_fold:
        return False

    turns = memory.turns_by_ids(conversation_id, to_fold)
    if not turns:
        return False

    previous = get_summary(conversation_id) or ""
    merged = _merge_summary(previous, turns)
    if not merged.strip():
        return False

    _record(conversation_id, twin_employee_id, merged, max(to_fold))
    return True


def colleague_context_block(
    conversation_id: str,
    *,
    label: str = "Colleague",
) -> str:
    """Context summary for owner colleague lookup (no verbatim chat)."""
    summary = get_summary(conversation_id)
    if not summary:
        return ""
    return f"Context from stand-in chat with {label}:\n{summary}"
