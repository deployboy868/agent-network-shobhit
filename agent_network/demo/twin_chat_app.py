"""
Browser chat UI for talking to a digital twin.

Run:
  AGENT_NETWORK_MODE=mock streamlit run agent_network/demo/twin_chat_app.py
  streamlit run agent_network/demo/twin_chat_app.py   # uses .env mode
"""

from __future__ import annotations

import streamlit as st

from agent_network import memory
from agent_network.agent.llm_router import is_llm_enabled, llm_backend_label
from agent_network.agent.twin_chat import TwinChatSession
from agent_network.audit import read_twin_audit
from agent_network.config import get_mode, is_mock_mode, llm_provider
from agent_network.mcp.mock_tools import MockTeams
from agent_network.models import TwinStandInPolicy
from agent_network.registry import (
    DEMO_INTERN_ID,
    DEMO_MANAGER_ID,
    SAMPLE_EMPLOYEES,
    employee_by_id,
    set_employee_absent,
)
from agent_network.standin_policy import get_policy, policy_summary, set_policy
from agent_network.ticket_approval import format_pending_list, list_pending

st.set_page_config(
    page_title="Agent Social Network",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="expanded",
)

EXAMPLE_PROMPTS = [
    "list my tickets",
    "list merge requests",
    "delegate handbook fix to assignee",
    "help",
]

OWNER_PROMPTS = [
    "go absent",
    "notify and confirm with me before creating tickets",
    "pending approvals",
    "stand-in settings",
    "what happened while I was away?",
]


def _employee_options() -> dict[str, str]:
    return {e.name: e.employee_id for e in SAMPLE_EMPLOYEES}


def _sync_absent_toggle() -> None:
    twin_id = st.session_state.get("_owner_twin_id")
    if twin_id:
        set_employee_absent(twin_id, bool(st.session_state.get("absent_toggle", False)))


def _ensure_policy_widget_state(twin_id: str) -> None:
    """Initialize or refresh checkbox state before widgets render."""
    policy = get_policy(twin_id)
    if st.session_state.pop("_sync_policy_widgets", False):
        st.session_state["policy_can_delegate"] = policy.can_delegate
        st.session_state["policy_notify_delegate"] = policy.notify_on_delegate
        st.session_state["policy_require_ticket_approval"] = policy.require_ticket_approval
    elif "policy_can_delegate" not in st.session_state:
        st.session_state["policy_can_delegate"] = policy.can_delegate
        st.session_state["policy_notify_delegate"] = policy.notify_on_delegate
        st.session_state["policy_require_ticket_approval"] = policy.require_ticket_approval


def _sync_delegate_policy() -> None:
    twin_id = st.session_state.get("_owner_twin_id")
    if not twin_id:
        return
    policy = get_policy(twin_id)
    set_policy(
        twin_id,
        TwinStandInPolicy(
            can_delegate=bool(st.session_state.get("policy_can_delegate", policy.can_delegate)),
            notify_on_delegate=bool(
                st.session_state.get("policy_notify_delegate", policy.notify_on_delegate)
            ),
            require_ticket_approval=bool(
                st.session_state.get(
                    "policy_require_ticket_approval", policy.require_ticket_approval
                )
            ),
            default_delegate_to=policy.default_delegate_to,
            instructions=policy.instructions,
            absence_windows=policy.absence_windows,
        ),
    )


def _load_messages_from_memory(chat: TwinChatSession) -> list[dict[str, str]]:
    """Hydrate Streamlit UI from persisted SQLite chat (survives refresh / new tab)."""
    stored = memory.recent(chat.conversation_id, limit=200)
    if stored:
        return stored
    return [{"role": "assistant", "content": chat.greeting()}]


def _sync_owner_chat_from_db(chat: TwinChatSession) -> None:
    """Owner chat: pull proactive twin messages written while they were on another device."""
    if not chat.is_owner_session():
        return
    stored = memory.recent(chat.conversation_id, limit=200)
    if stored:
        st.session_state.messages = stored


def _init_session(twin_id: str, requester_id: str) -> None:
    key = f"{twin_id}:{requester_id}"
    if st.session_state.get("session_key") != key:
        st.session_state.session_key = key
        st.session_state.chat = TwinChatSession(twin_id, requester_employee_id=requester_id)
        st.session_state.messages = _load_messages_from_memory(st.session_state.chat)
    elif "messages" not in st.session_state:
        st.session_state.messages = _load_messages_from_memory(st.session_state.chat)


def _ollama_reachable() -> bool:
    if llm_provider() != "ollama":
        return True
    try:
        from urllib.request import urlopen

        from agent_network.config import ollama_base_url

        base = ollama_base_url().rstrip("/").removesuffix("/v1")
        with urlopen(f"{base}/api/tags", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> None:
    st.title("Agent Social Network")
    st.caption("Coordinate with your twin — or message a colleague's twin when they're away.")

    emp_opts = _employee_options()

    with st.sidebar:
        st.header("Session")
        requester_name = st.selectbox(
            "You are",
            options=list(emp_opts.keys()),
            index=list(emp_opts.values()).index(DEMO_INTERN_ID),
        )
        requester_id = emp_opts[requester_name]

        twin_labels = {
            f"{e.name} ({'absent' if e.is_absent else 'present'})": e.employee_id
            for e in SAMPLE_EMPLOYEES
        }
        default_twin_label = next(
            lbl for lbl, eid in twin_labels.items() if eid == DEMO_MANAGER_ID
        )
        twin_label = st.selectbox(
            "Talking to twin of",
            options=list(twin_labels.keys()),
            index=list(twin_labels.keys()).index(default_twin_label),
        )
        twin_id = twin_labels[twin_label]
        twin_emp = employee_by_id(twin_id)
        if not twin_emp:
            st.error("Unknown twin employee.")
            return

        is_owner = requester_id == twin_id

        st.divider()
        st.markdown(f"**Twin status:** {'Absent — stand-in' if twin_emp.is_absent else 'Present'}")
        st.markdown(f"**Twin skills:** {', '.join(s.value for s in twin_emp.skills)}")
        st.markdown(f"**Mode:** `{get_mode()}`" + (" (mock)" if is_mock_mode() else " (live)"))
        if is_llm_enabled():
            st.markdown(f"**Brain:** LLM — {llm_backend_label()}")
            if llm_provider() == "ollama" and not _ollama_reachable():
                st.warning(
                    "Ollama not running. Start it with: `brew services start ollama`"
                )
        else:
            st.markdown("**Brain:** keyword router (set `OLLAMA_ENABLED=true` for local LLM)")

        if is_owner:
            st.divider()
            st.subheader("Your stand-in controls")
            st.session_state["_owner_twin_id"] = twin_id
            st.toggle(
                "Mark me absent",
                value=twin_emp.is_absent,
                key="absent_toggle",
                on_change=_sync_absent_toggle,
            )

            _ensure_policy_widget_state(twin_id)
            st.checkbox(
                "Twin can delegate",
                key="policy_can_delegate",
                on_change=_sync_delegate_policy,
            )
            st.checkbox(
                "Notify me on Teams when twin delegates",
                key="policy_notify_delegate",
                on_change=_sync_delegate_policy,
            )
            st.checkbox(
                "Confirm with me before creating tickets for colleagues",
                key="policy_require_ticket_approval",
                on_change=_sync_delegate_policy,
            )

            pending = list_pending(twin_id)
            if pending:
                st.divider()
                st.subheader("Pending ticket approvals")
                st.warning(
                    f"{len(pending)} request(s) waiting — proactive notify already sent."
                )
                for item in pending:
                    who = employee_by_id(item["requester_employee_id"])
                    who_name = who.name if who else item["requester_employee_id"]
                    st.markdown(
                        f"**{item['ref_code']}** — {who_name}: \"{item['title']}\""
                    )
                st.caption("In chat: `approve TA-1` or `reject TA-1`")
                with st.expander("Full pending list"):
                    st.text(format_pending_list(twin_id))

            with st.expander("Activity while absent"):
                entries = read_twin_audit(twin_id, limit=8)
                if entries:
                    for e in reversed(entries):
                        st.caption(f"{e.get('action')}: {e.get('detail')}")
                else:
                    st.caption("No activity yet.")

            if is_mock_mode():
                notes = MockTeams.get_notifications(twin_emp.email)
                if notes:
                    st.divider()
                    st.subheader("Teams (mock) — proactive alerts")
                    for note in reversed(notes[-5:]):
                        st.info(note.get("text", note.get("message", str(note))))

        if st.button("Reset conversation"):
            chat = st.session_state.get("chat")
            if chat is not None:
                memory.clear(chat.conversation_id)
            for k in ("messages", "chat", "session_key"):
                st.session_state.pop(k, None)
            for k in ("policy_can_delegate", "policy_notify_delegate", "policy_require_ticket_approval", "_sync_policy_widgets"):
                st.session_state.pop(k, None)
            st.rerun()

        st.divider()
        st.markdown("**Try asking:**")
        prompts = OWNER_PROMPTS + EXAMPLE_PROMPTS if is_owner else EXAMPLE_PROMPTS
        for prompt in prompts:
            st.code(prompt, language=None)

        if is_owner:
            with st.expander("Stand-in policy text"):
                st.text(policy_summary(twin_id))

    _init_session(twin_id, requester_id)

    if requester_id == twin_id:
        _sync_owner_chat_from_db(st.session_state.chat)

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Message the twin…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.spinner("Thinking…"):
            reply = st.session_state.chat.handle(prompt)
        st.session_state.messages.append({"role": "assistant", "content": reply})
        if is_owner:
            st.session_state["_sync_policy_widgets"] = True
        st.rerun()


# Streamlit always executes this file top-to-bottom; do not guard with __name__.
main()
