"""
Resolve whether an employee is effectively absent.

Sources, in order:
  1. Manual flag (Employee.is_absent) — owner toggled "go absent".
  2. Scheduled absence windows (owner declared time periods).
  3. Microsoft Teams presence (Away/Offline/DoNotDisturb) — when Graph is configured.

The twin stands in whenever any source says the person is unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from agent_network.config import teams_presence_enabled
from agent_network.models import AbsenceWindow
from agent_network.registry import employee_by_id

logger = logging.getLogger(__name__)

# Teams presence availability values that mean "treat as absent".
_AWAY_PRESENCE = {"Away", "BeRightBack", "Offline", "PresenceUnknown"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def active_absence_window(
    employee_id: str, when: Optional[datetime] = None
) -> Optional[AbsenceWindow]:
    from agent_network.standin_policy import get_policy

    when = when or _now()
    policy = get_policy(employee_id)
    for window in policy.absence_windows:
        try:
            if window.contains(when):
                return window
        except TypeError:
            continue
    return None


def teams_presence(employee_id: str) -> Optional[str]:
    """Return Teams availability string, or None if unavailable/not configured."""
    if not teams_presence_enabled():
        return None
    emp = employee_by_id(employee_id)
    if not emp:
        return None
    try:
        from agent_network.teams.graph_presence import get_presence_by_email

        return get_presence_by_email(emp.email)
    except Exception as e:  # pragma: no cover - network/credentials dependent
        logger.warning("Teams presence lookup failed for %s: %s", employee_id, e)
        return None


def is_effectively_absent(employee_id: str, when: Optional[datetime] = None) -> bool:
    emp = employee_by_id(employee_id)
    if not emp:
        return False
    if emp.is_absent:
        return True
    if active_absence_window(employee_id, when):
        return True
    presence = teams_presence(employee_id)
    if presence and presence in _AWAY_PRESENCE:
        return True
    return False


def absence_reason(employee_id: str, when: Optional[datetime] = None) -> str:
    emp = employee_by_id(employee_id)
    if not emp:
        return "unknown employee"
    if emp.is_absent:
        return "manually marked absent"
    window = active_absence_window(employee_id, when)
    if window:
        note = f" ({window.note})" if window.note else ""
        return f"scheduled absence until {window.end.date()}{note}"
    presence = teams_presence(employee_id)
    if presence and presence in _AWAY_PRESENCE:
        return f"Teams presence: {presence}"
    return "present"
