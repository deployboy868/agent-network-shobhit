"""
Persistent owner rules — dynamic standing instructions per twin.

Separate from:
- chat memory (verbatim thread transcript)
- context memory (folded conversation summary)
- owner_briefings legacy table (deprecated for prompt injection)

Each rule is a durable, always-on instruction the twin applies in every session.
Only the twin's owner may add, update, or revoke rules (enforced at call sites).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from agent_network.config import memory_db_path

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_active_path: Optional[str] = None


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            twin_employee_id TEXT NOT NULL,
            rule_text TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_owner_rules_twin "
        "ON owner_rules (twin_employee_id, active, id)"
    )
    _ensure_policy_tags_column(conn)
    conn.commit()
    return conn


def _ensure_policy_tags_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(owner_rules)").fetchall()}
    if "policy_tags" not in cols:
        conn.execute("ALTER TABLE owner_rules ADD COLUMN policy_tags TEXT NOT NULL DEFAULT '{}'")


def _get_conn() -> sqlite3.Connection:
    global _conn, _active_path
    path = memory_db_path()
    if _conn is None or _active_path != path:
        _conn = _connect(path)
        _active_path = path
    return _conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_policy_tags(raw: Any) -> dict[str, bool]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {k: bool(v) for k, v in raw.items() if k in ("require_ticket_approval", "can_delegate")}
    try:
        data = json.loads(str(raw))
        if isinstance(data, dict):
            return {
                k: bool(v)
                for k, v in data.items()
                if k in ("require_ticket_approval", "can_delegate")
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def list_active_rules(twin_employee_id: str) -> list[dict]:
    """Return active rules oldest-first: [{id, rule_text, policy_tags}, ...]."""
    if not twin_employee_id:
        return []
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, rule_text, policy_tags FROM owner_rules "
            "WHERE twin_employee_id = ? AND active = 1 ORDER BY id",
            (twin_employee_id,),
        ).fetchall()
    return [
        {
            "id": int(r[0]),
            "rule_text": r[1],
            "policy_tags": _parse_policy_tags(r[2] if len(r) > 2 else "{}"),
        }
        for r in rows
    ]


def add_rule(
    twin_employee_id: str,
    rule_text: str,
    *,
    policy_tags: Optional[dict[str, bool]] = None,
) -> Optional[int]:
    text = (rule_text or "").strip()
    if not twin_employee_id or not text:
        return None
    tags_json = json.dumps(policy_tags or {})
    ts = _now()
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO owner_rules "
            "(twin_employee_id, rule_text, active, created_at, updated_at, policy_tags) "
            "VALUES (?, ?, 1, ?, ?, ?)",
            (twin_employee_id, text, ts, ts, tags_json),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_rule(
    twin_employee_id: str,
    rule_id: int,
    rule_text: str,
    *,
    policy_tags: Optional[dict[str, bool]] = None,
) -> bool:
    text = (rule_text or "").strip()
    if not twin_employee_id or not rule_id or not text:
        return False
    tags_json = json.dumps(policy_tags) if policy_tags is not None else None
    with _lock:
        conn = _get_conn()
        if tags_json is not None:
            cur = conn.execute(
                "UPDATE owner_rules SET rule_text = ?, policy_tags = ?, updated_at = ? "
                "WHERE id = ? AND twin_employee_id = ? AND active = 1",
                (text, tags_json, _now(), rule_id, twin_employee_id),
            )
        else:
            cur = conn.execute(
                "UPDATE owner_rules SET rule_text = ?, updated_at = ? "
                "WHERE id = ? AND twin_employee_id = ? AND active = 1",
                (text, _now(), rule_id, twin_employee_id),
            )
        conn.commit()
        return cur.rowcount > 0


def revoke_rule(twin_employee_id: str, rule_id: int) -> bool:
    if not twin_employee_id or not rule_id:
        return False
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "UPDATE owner_rules SET active = 0, updated_at = ? "
            "WHERE id = ? AND twin_employee_id = ? AND active = 1",
            (_now(), rule_id, twin_employee_id),
        )
        conn.commit()
        return cur.rowcount > 0


def _question_keywords(lower: str) -> set[str]:
    stop = {
        "can",
        "you",
        "tell",
        "where",
        "what",
        "how",
        "the",
        "get",
        "for",
        "about",
        "this",
        "that",
        "please",
        "would",
        "could",
        "should",
        "need",
        "want",
        "know",
        "features",
        "feature",
    }
    words = set(re.findall(r"[a-z0-9]+", lower))
    keywords = {w for w in words if len(w) > 2 and w not in stop}
    if any(x in lower for x in ("copilot", "copilot studio")):
        keywords.update({"copilot", "studio", "generative"})
    if "gen ai" in lower or "generative ai" in lower:
        keywords.update({"generative", "gen", "ai"})
    if "myaccess" in lower or "my access" in lower:
        keywords.update({"myaccess", "access"})
    if "sprint" in lower and "planner" in lower:
        keywords.update({"sprint", "planner"})
    return keywords


def _rule_match_score(user_keywords: set[str], rule_text: str) -> int:
    hay = rule_text.lower()
    if not user_keywords:
        return 0
    score = sum(1 for k in user_keywords if k in hay)
    if "copilot" in user_keywords and "copilot" in hay:
        score += 2
    if "myaccess" in hay and ("access" in user_keywords or "myaccess" in user_keywords):
        score += 2
    return score


def match_rules_for_colleague_question(
    twin_employee_id: str, user_message: str
) -> list[dict]:
    """Rank owner standing rules that apply to a colleague's question."""
    lower = (user_message or "").lower().strip()
    if not lower or not twin_employee_id:
        return []
    rules = list_active_rules(twin_employee_id)
    if not rules:
        return []

    user_keywords = _question_keywords(lower)
    scored: list[tuple[int, dict]] = []
    for rule in rules:
        score = _rule_match_score(user_keywords, rule["rule_text"])
        if score >= 2:
            scored.append((score, rule))
    scored.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [rule for _, rule in scored]


def format_rule_answer_for_colleague(owner_name: str, rule_text: str) -> str:
    """Turn a standing rule into a direct answer for a colleague (no LLM required)."""
    text = (rule_text or "").strip()
    lower = text.lower()
    guidance = text
    for pattern in (
        r"^when\s+.+?\s+asks?\s+(?:about\s+)?",
        r"^if\s+(?:someone|they|people)\s+asks?\s+(?:about\s+)?",
        r"^when\s+.+?\s+asks?\s+for\s+",
    ):
        stripped = re.sub(pattern, "", guidance, count=1, flags=re.I).strip()
        if stripped != guidance:
            guidance = stripped
            lower = guidance.lower()
            break
    for prefix in (
        "tell people wanting ",
        "tell people ",
        "tell them ",
        "tell interns ",
        "tell the intern ",
        "direct them ",
        "point them ",
        "ask them ",
        "send them ",
    ):
        if lower.startswith(prefix):
            guidance = guidance[len(prefix) :].strip(" :.-")
            break
        if prefix in lower:
            idx = lower.index(prefix)
            guidance = guidance[idx + len(prefix) :].strip(" :.-")
            break
    guidance = guidance.rstrip(".")
    if guidance.lower().startswith("to "):
        guidance = guidance[3:].strip()
    first = guidance[:1].upper() + guidance[1:] if guidance else text
    return (
        f"{owner_name} left me guidance on this while they're away: {first}."
    )


def find_similar_active_rule(
    twin_employee_id: str, rule_text: str
) -> Optional[dict]:
    """Return an active rule that substantially overlaps the candidate text."""
    needle = (rule_text or "").lower().strip()
    if not needle:
        return None
    for rule in list_active_rules(twin_employee_id):
        hay = rule["rule_text"].lower()
        if needle in hay or hay in needle:
            return rule
        needle_words = {w for w in needle.split() if len(w) > 3}
        hay_words = {w for w in hay.split() if len(w) > 3}
        if needle_words and hay_words:
            overlap = len(needle_words & hay_words) / max(len(needle_words), 1)
            if overlap >= 0.5:
                return rule
    return None


def count_active(twin_employee_id: str) -> int:
    if not twin_employee_id:
        return 0
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM owner_rules WHERE twin_employee_id = ? AND active = 1",
            (twin_employee_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def clear(twin_employee_id: str) -> int:
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "DELETE FROM owner_rules WHERE twin_employee_id = ?",
            (twin_employee_id,),
        )
        conn.commit()
        return cur.rowcount


def clear_all() -> int:
    with _lock:
        conn = _get_conn()
        cur = conn.execute("DELETE FROM owner_rules")
        conn.commit()
        return cur.rowcount


def reset_instruction_memory() -> None:
    global _conn, _active_path
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None
        _active_path = None


def prompt_block(twin_employee_id: str, owner_name: str) -> str:
    """Injected into every twin session — all active owner rules."""
    from agent_network.standin_policy import get_policy

    rules = list_active_rules(twin_employee_id)
    policy = get_policy(twin_employee_id)
    policy_text = (policy.instructions or "").strip()

    if not rules and not policy_text:
        return ""

    lines = [
        f"Owner rules from {owner_name} — follow in EVERY conversation "
        f"(with {owner_name} and with colleagues). Reason from these; do not ignore them:",
    ]
    for rule in rules:
        text = rule["rule_text"].replace("\n", " ").strip()
        if len(text) > 500:
            text = text[:497] + "..."
        tags = rule.get("policy_tags") or {}
        tag_note = ""
        if tags.get("require_ticket_approval"):
            tag_note = " [requires owner approval before creating tickets]"
        elif tags.get("can_delegate") is False:
            tag_note = " [no delegating tickets]"
        lines.append(f"  • [{rule['id']}] {text}{tag_note}")

    if policy_text and not _policy_in_rules(rules, policy_text):
        lines.append(f"  • (policy) {policy_text}")

    lines.append(
        "Apply topic-specific guidance when colleagues ask — tone, what to offer, "
        "what to avoid, and when to escalate to the owner."
    )
    return "\n".join(lines)


def _policy_in_rules(rules: list[dict], policy_text: str) -> bool:
    needle = policy_text.lower().strip()
    if not needle:
        return True
    for rule in rules:
        if needle in rule.get("rule_text", "").lower():
            return True
    return False


def process_owner_message(
    twin_employee_id: str,
    user_message: str,
    assistant_reply: str = "",
) -> dict:
    """
    Classify an owner↔twin message and mutate owner_rules when appropriate.

    Returns a summary dict: {applied, operations, message_kind, reasoning, policy_effects}.
    Only call from owner sessions.
    """
    from agent_network.agent.owner_rule_classifier import (
        classify_owner_message,
        derive_policy_from_rules,
    )
    from agent_network.standin_policy import get_policy, set_policy

    classification = classify_owner_message(
        twin_employee_id, user_message, assistant_reply
    )
    applied: list[dict] = []

    for op in classification.operations:
        action = op.get("action")
        if action == "none":
            continue
        tags = op.get("policy_tags") if isinstance(op.get("policy_tags"), dict) else None
        if action == "add":
            text = str(op.get("rule_text", "")).strip()
            if not text:
                continue
            similar = find_similar_active_rule(twin_employee_id, text)
            if similar:
                update_rule(twin_employee_id, similar["id"], text, policy_tags=tags)
                applied.append(
                    {
                        "action": "update",
                        "rule_id": similar["id"],
                        "rule_text": text,
                        "policy_tags": tags or {},
                    }
                )
            else:
                rid = add_rule(twin_employee_id, text, policy_tags=tags)
                if rid:
                    applied.append(
                        {
                            "action": "add",
                            "rule_id": rid,
                            "rule_text": text,
                            "policy_tags": tags or {},
                        }
                    )
        elif action == "update":
            rid = op.get("rule_id")
            text = str(op.get("rule_text", "")).strip()
            if rid and text and update_rule(
                twin_employee_id, int(rid), text, policy_tags=tags
            ):
                applied.append(
                    {
                        "action": "update",
                        "rule_id": int(rid),
                        "rule_text": text,
                        "policy_tags": tags or {},
                    }
                )
        elif action == "revoke":
            rid = op.get("rule_id")
            if rid and revoke_rule(twin_employee_id, int(rid)):
                applied.append({"action": "revoke", "rule_id": int(rid)})

    # Apply immediate policy hints from classification, then reconcile from all rules.
    effects = classification.policy_effects
    if effects:
        policy = get_policy(twin_employee_id)
        changed = False
        if effects.get("require_ticket_approval") is not None:
            policy.require_ticket_approval = bool(effects["require_ticket_approval"])
            changed = True
        if effects.get("can_delegate") is not None:
            policy.can_delegate = bool(effects["can_delegate"])
            changed = True
        if changed:
            set_policy(twin_employee_id, policy)

    derived = derive_policy_from_rules(twin_employee_id)

    return {
        "applied": bool(applied),
        "operations": applied,
        "message_kind": classification.message_kind,
        "reasoning": classification.reasoning,
        "policy_effects": derived,
    }
