"""Stand-in policy and absence state for digital twins."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from agent_network.models import AbsenceWindow, TwinStandInPolicy
from agent_network.registry import (
    DEMO_ASSIGNEE_ID,
    employee_display_name,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_POLICY_FILE = _PROJECT_ROOT / ".twin-standin-policies.json"

_policies: dict[str, TwinStandInPolicy] = {}


def _default_policy() -> TwinStandInPolicy:
    return TwinStandInPolicy(default_delegate_to=DEMO_ASSIGNEE_ID)


def _load_from_disk() -> None:
    global _policies
    if not _POLICY_FILE.exists():
        return
    try:
        raw = json.loads(_POLICY_FILE.read_text(encoding="utf-8"))
        _policies = {
            emp_id: TwinStandInPolicy.model_validate(data)
            for emp_id, data in raw.items()
        }
    except (json.JSONDecodeError, ValueError):
        _policies = {}


def _save_to_disk() -> None:
    payload = {
        emp_id: policy.model_dump(mode="json") for emp_id, policy in _policies.items()
    }
    _POLICY_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


_load_from_disk()


def get_policy(employee_id: str) -> TwinStandInPolicy:
    if employee_id not in _policies:
        _policies[employee_id] = _default_policy()
    return _policies[employee_id]


def set_policy(employee_id: str, policy: TwinStandInPolicy) -> None:
    _policies[employee_id] = policy
    _save_to_disk()


def policy_summary(employee_id: str) -> str:
    policy = get_policy(employee_id)
    delegate_to = (
        employee_display_name(policy.default_delegate_to)
        if policy.default_delegate_to
        else "assignee"
    )
    lines = [
        f"Stand-in policy for {employee_display_name(employee_id)}:",
        f"  • Can delegate: {'yes' if policy.can_delegate else 'no'}",
        f"  • Notify me on Teams when twin delegates: "
        f"{'yes' if policy.notify_on_delegate else 'no'}",
        f"  • Confirm with me before creating tickets for colleagues: "
        f"{'yes' if policy.require_ticket_approval else 'no'}",
        f"  • Default delegate target: {delegate_to}",
    ]
    if policy.instructions:
        lines.append(f"  • My instructions: {policy.instructions}")
    if policy.absence_windows:
        lines.append("  • Scheduled away:")
        for w in policy.absence_windows:
            note = f" — {w.note}" if w.note else ""
            lines.append(f"      {w.start.date()} → {w.end.date()}{note}")
    return "\n".join(lines)


def set_instructions(employee_id: str, instructions: str) -> str:
    policy = get_policy(employee_id)
    policy.instructions = instructions.strip()
    set_policy(employee_id, policy)
    return policy.instructions


def add_absence_window(
    employee_id: str, start: datetime, end: datetime, note: str = ""
) -> str:
    policy = get_policy(employee_id)
    policy.absence_windows.append(AbsenceWindow(start=start, end=end, note=note))
    set_policy(employee_id, policy)
    return f"{start.date()} → {end.date()}"


def clear_absence_windows(employee_id: str) -> None:
    policy = get_policy(employee_id)
    policy.absence_windows = []
    set_policy(employee_id, policy)


def reset_standin_policies() -> None:
    global _policies
    _policies = {}
    if _POLICY_FILE.exists():
        _POLICY_FILE.unlink()


def update_policy_from_message(employee_id: str, lower: str) -> Optional[str]:
    """Parse simple rule updates from owner chat."""
    policy = get_policy(employee_id)
    changed = False

    if "no notify" in lower or "notify off" in lower:
        policy.notify_on_delegate = False
        changed = True
    if "notify on" in lower or "notify me" in lower:
        policy.notify_on_delegate = True
        changed = True
    if "no delegate" in lower or "can't delegate" in lower or "cannot delegate" in lower:
        policy.can_delegate = False
        changed = True
    if any(
        p in lower
        for p in (
            "don't assign",
            "do not assign",
            "dont assign",
            "don't delegate",
            "do not delegate",
            "never assign",
            "never delegate",
        )
    ):
        policy.can_delegate = False
        changed = True
    if "can delegate" in lower or "allow delegate" in lower:
        policy.can_delegate = True
        changed = True
    if any(
        p in lower
        for p in (
            "confirm before",
            "notify me before",
            "notify and confirm",
            "ask me before",
            "approval before",
            "check with me before",
        )
    ) and "ticket" in lower:
        policy.require_ticket_approval = True
        changed = True
    if "no ticket approval" in lower or "auto create ticket" in lower:
        policy.require_ticket_approval = False
        changed = True
    if "assignee" in lower and "default" in lower:
        policy.default_delegate_to = DEMO_ASSIGNEE_ID
        changed = True

    if not changed:
        return None
    set_policy(employee_id, policy)
    return policy_summary(employee_id)
