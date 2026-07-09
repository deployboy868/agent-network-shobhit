"""Load settings from environment (.env)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)


def get_mode() -> str:
    """mock | live — mock is default for internship MVP."""
    return os.getenv("AGENT_NETWORK_MODE", "mock").strip().lower()


def is_mock_mode() -> bool:
    return get_mode() != "live"


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(
            f"Missing {name} in .env (required when AGENT_NETWORK_MODE=live). "
            f"See .env.example."
        )
    return value


def jira_base_url() -> str:
    return _require("JIRA_BASE_URL").rstrip("/")


def jira_email() -> str:
    return _require("JIRA_EMAIL")


def jira_api_token() -> str:
    return _require("JIRA_API_TOKEN")


def jira_project_key() -> str:
    return _require("JIRA_PROJECT_KEY")


def jira_issue_type() -> str:
    return os.getenv("JIRA_ISSUE_TYPE", "Task").strip() or "Task"


def jira_safe_prefix() -> str:
    """
    Prefix added to every ticket WE create. Assign/close only allowed on
    tickets with this prefix in the summary (protects old project issues).
    """
    return os.getenv("JIRA_SAFE_PREFIX", "[Agent-Network-TEST]").strip()


def jira_project_key_required() -> str:
    """Project we are allowed to create in; modifications blocked for other projects."""
    return jira_project_key()


def jira_done_transition() -> str:
    """
    Optional exact transition button name in Jira (e.g. Close, Resolve, Complete).
    Run discover_jira_transitions.py on an open issue to see options.
    """
    return os.getenv("JIRA_DONE_TRANSITION", "").strip()


def jira_close_workflow() -> list[str]:
    """
    Enable multi-step close for legacy workflows (LST: Need Review -> ... -> Closed).
    Set JIRA_CLOSE_WORKFLOW=enabled, or comma-separated button hints as fallback.
    """
    raw = os.getenv("JIRA_CLOSE_WORKFLOW", "").strip()
    if not raw:
        return []
    if raw.lower() in ("enabled", "true", "yes", "1", "on"):
        # LST UI: In Progress -> IN REVIEW; In Review -> CLOSED
        return ["IN PROGRESS", "IN REVIEW", "CLOSED"]
    return [s.strip() for s in raw.split(",") if s.strip()]


def is_demo_safe_mode() -> bool:
    """
    When true (default): live demos assign tickets to JIRA_EMAIL (you) only,
    never to colleagues; no Teams pings.
    """
    val = os.getenv("JIRA_DEMO_SAFE_MODE", "true").strip().lower()
    return val in ("1", "true", "yes", "on")


def gitlab_base_url() -> str:
    return os.getenv("GITLAB_BASE_URL", "").strip().rstrip("/")


def gitlab_private_token() -> str:
    return os.getenv("GITLAB_PRIVATE_TOKEN", "").strip()


def gitlab_project_id() -> str:
    return os.getenv("GITLAB_PROJECT_ID", "").strip()


def gitlab_default_branch() -> str:
    """Optional override; if empty, LiveGitLab reads default_branch from project API."""
    return os.getenv("GITLAB_DEFAULT_BRANCH", "").strip()


def llm_provider() -> str:
    """groq | grok | ollama | openai | none. LLM_PROVIDER overrides auto-detection."""
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit in ("groq", "grok", "ollama", "openai"):
        return explicit
    if explicit == "none":
        return "none"
    if os.getenv("OLLAMA_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        return "ollama"
    if os.getenv("GROQ_API_KEY", "").strip():
        return "groq"
    if os.getenv("GROK_API_KEY", "").strip():
        return "grok"
    if os.getenv("OPENAI_API_KEY", "").strip():
        return "openai"
    return "none"


def is_llm_enabled() -> bool:
    return llm_provider() != "none"


def ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip().rstrip("/")


def ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", "llama3.1").strip() or "llama3.1"


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def groq_api_key() -> str:
    return os.getenv("GROQ_API_KEY", "").strip()


def groq_base_url() -> str:
    return os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").strip().rstrip("/")


def groq_model() -> str:
    return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"


def grok_api_key() -> str:
    return os.getenv("GROK_API_KEY", "").strip()


def grok_base_url() -> str:
    return os.getenv("GROK_BASE_URL", "https://api.x.ai/v1").strip().rstrip("/")


def grok_model() -> str:
    return os.getenv("GROK_MODEL", "grok-2-latest").strip() or "grok-2-latest"


# --- Conversation memory ---
def memory_db_path() -> str:
    default = str(_PROJECT_ROOT / ".twin-memory.db")
    return os.getenv("TWIN_MEMORY_DB", default).strip() or default


def memory_context_turns() -> int:
    try:
        return int(os.getenv("TWIN_MEMORY_TURNS", "10"))
    except ValueError:
        return 10


def owner_memory_turns() -> int:
    """How many owner↔twin briefing turns to inject into every session."""
    try:
        return int(os.getenv("TWIN_OWNER_MEMORY_TURNS", "40"))
    except ValueError:
        return 40


def owner_colleague_memory_turns() -> int:
    """Max turns per colleague conversation shown to the owner twin."""
    try:
        return int(os.getenv("TWIN_OWNER_COLLEAGUE_MEMORY_TURNS", "30"))
    except ValueError:
        return 30


def context_summary_max_chars() -> int:
    """Cap stored derived context per conversation."""
    try:
        return int(os.getenv("TWIN_CONTEXT_MAX_CHARS", "2400"))
    except ValueError:
        return 2400


def context_recent_verbatim_turns() -> int:
    """How many latest chat turns stay verbatim (not folded into context)."""
    return memory_context_turns()


# --- Microsoft Teams / Graph (live deploy) ---
def teams_app_id() -> str:
    return os.getenv("MICROSOFT_APP_ID", "").strip()


def teams_app_password() -> str:
    return os.getenv("MICROSOFT_APP_PASSWORD", "").strip()


def bot_emulator_mode() -> bool:
    """
    Local Bot Framework Emulator without Azure Bot credentials.
    Auto-enabled when MICROSOFT_APP_ID/PASSWORD are unset; override with BOT_EMULATOR_MODE.
    """
    explicit = os.getenv("BOT_EMULATOR_MODE", "").strip().lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    if explicit in ("0", "false", "no", "off"):
        return False
    return not teams_app_id() and not teams_app_password()


def default_requester_id() -> str:
    return os.getenv("DEFAULT_REQUESTER_ID", "").strip()


def graph_tenant_id() -> str:
    return os.getenv("TENANT_ID", "").strip()


def graph_client_id() -> str:
    return os.getenv("GRAPH_CLIENT_ID", os.getenv("MICROSOFT_APP_ID", "")).strip()


def graph_client_secret() -> str:
    return os.getenv("GRAPH_CLIENT_SECRET", os.getenv("MICROSOFT_APP_PASSWORD", "")).strip()


def teams_presence_enabled() -> bool:
    return bool(graph_tenant_id() and graph_client_id() and graph_client_secret())
