"""Extract a human-meaningful Jira ticket title from colleague create-ticket requests."""

from __future__ import annotations

import re
from typing import Optional

# Titles that are pronouns / back-references, not real work names.
_INVALID_TITLES = frozenset(
    {
        "it",
        "this",
        "that",
        "same",
        "one",
        "this work",
        "that work",
        "the same",
        "the task",
        "this task",
        "that task",
    }
)

_ASSIGNED_CREATE = re.compile(
    r"assigned (?:the )?task to (?:create|build|make|develop)\s+(?:a\s+)?"
    r"(.+?)(?:\s+by\b|,|\s+can you|\s+could you|\s+please|$)",
    re.I,
)
_ASSIGNED_TASK_OF = re.compile(
    r"assigned (?:me )?(?:the )?task of (?:creating|building|making)\s+(?:a\s+)?"
    r"(.+?)(?:,|\s+can you|\s+could you|$)",
    re.I,
)
_TICKET_FOR = re.compile(
    r"(?:ticket\s+for|ticket\s+on|create a ticket for)\s+"
    r"(?!the same\b|same\b|it\b|this\b|that\b)"
    r"(.+?)(?:\?|$)",
    re.I,
)
_SPRINT_PLANNER = re.compile(r"\b(sprint\s+planner)\b", re.I)
_TITLE_CASE_PHRASE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


def _clean_title(raw: str) -> str:
    title = (raw or "").strip().rstrip(".?!").strip()
    title = re.sub(r"^(?:a|an|the)\s+", "", title, flags=re.I)
    if title.lower() in _INVALID_TITLES:
        return ""
    if len(title) <= 2:
        return ""
    if title.islower():
        return title.title()
    return title


def extract_ticket_title_from_request(text: str) -> Optional[str]:
    """
    Pull the work item name from a natural-language create-ticket request.
    Prefers explicit task descriptions over trailing 'for the same' pronouns.
    """
    if not (text or "").strip():
        return None

    m = _ASSIGNED_CREATE.search(text)
    if m:
        title = _clean_title(m.group(1))
        if title:
            return title

    m = _ASSIGNED_TASK_OF.search(text)
    if m:
        title = _clean_title(m.group(1))
        if title:
            return title

    m = _SPRINT_PLANNER.search(text)
    if m:
        return m.group(1).title()

    m = _TICKET_FOR.search(text)
    if m:
        title = _clean_title(m.group(1))
        if title:
            return title

    m = _TITLE_CASE_PHRASE.search(text)
    if m:
        title = _clean_title(m.group(1))
        if title:
            return title

    return None


def normalize_ticket_title(title: str, user_message: str = "") -> str:
    """
    Sanitize an LLM- or regex-provided title; re-extract from message if it's a pronoun.
    """
    cleaned = _clean_title(title)
    if cleaned and cleaned.lower() not in _INVALID_TITLES:
        return cleaned
    if user_message:
        extracted = extract_ticket_title_from_request(user_message)
        if extracted:
            return extracted
    return cleaned
