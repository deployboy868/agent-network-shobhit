"""Tests for derived conversation context (separate from verbatim chat)."""

import os
import tempfile
from unittest.mock import patch

from agent_network import context_memory, memory


def _with_temp_db(turns: str = "3"):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return patch.dict(
        os.environ,
        {
            "TWIN_MEMORY_DB": tmp.name,
            "TWIN_MEMORY_TURNS": turns,
            "LLM_PROVIDER": "none",
        },
    )


def test_chat_and_context_are_separate_stores():
    with _with_temp_db():
        memory.reset_memory()
        conv = "conv-ctx-1"
        memory.remember(conv, "user", "hello", "emp-manager")
        memory.remember(conv, "assistant", "hi there", "emp-manager")

        assert memory.history_count(conv) == 2
        assert context_memory.get_summary(conv) is None

        context_memory._record(conv, "emp-manager", "• User greeted; twin responded.", 1)
        summary = context_memory.get_summary(conv)
        assert summary is not None
        assert "greeted" in summary.lower()

        turns = memory.recent(conv)
        assert turns[0]["content"] == "hello"
        assert turns[1]["content"] == "hi there"
        memory.reset_memory()


def test_refresh_folds_old_turns_leaves_recent_verbatim():
    with _with_temp_db(turns="2"):
        memory.reset_memory()
        conv = "conv-fold"
        twin = "emp-manager"
        pairs = [
            ("user", "blocked on LST-10001 sprint planner"),
            ("assistant", "let me check that ticket"),
            ("user", "also need LST-10002 deploy help"),
            ("assistant", "noted both tickets"),
            ("user", "what about the wiki section"),
            ("assistant", "still working on wiki guidance"),
        ]
        for role, content in pairs:
            memory.remember(conv, role, content, twin)

        updated = context_memory.refresh_from_chat(conv, twin)
        assert updated is True
        summary = context_memory.get_summary(conv) or ""
        assert "LST-10001" in summary or "sprint planner" in summary.lower()

        recent = memory.recent(conv, limit=2)
        assert len(recent) == 2
        assert "wiki" in recent[-1]["content"].lower()

        assert context_memory.through_message_id(conv) >= 1
        memory.reset_memory()


def test_prompt_block_only_when_context_exists():
    with _with_temp_db():
        memory.reset_memory()
        conv = "conv-prompt"
        assert context_memory.prompt_block(conv) == ""
        context_memory._record(conv, None, "• Ticket LST-55 discussed.", 3)
        block = context_memory.prompt_block(conv)
        assert "Earlier in this conversation" in block
        assert "LST-55" in block
        memory.reset_memory()


def test_clear_chat_also_clears_context():
    with _with_temp_db():
        memory.reset_memory()
        conv = "conv-clear"
        memory.remember(conv, "user", "x", "emp-manager")
        context_memory._record(conv, "emp-manager", "• summary", 1)
        memory.clear(conv)
        assert memory.recent(conv) == []
        assert context_memory.get_summary(conv) is None
        memory.reset_memory()


def test_colleague_lookup_includes_derived_context():
    with _with_temp_db():
        memory.reset_memory()
        from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID

        conv = memory.conversation_id_for_colleague(DEMO_MANAGER_ID, DEMO_INTERN_ID)
        context_memory._record(
            conv,
            DEMO_MANAGER_ID,
            "• Intern blocked on sprint planner wiki section (LST-90001).",
            2,
        )
        memory.remember(conv, "user", "latest ping about handbook", DEMO_MANAGER_ID)

        block = memory.colleague_activity_prompt_block(
            DEMO_MANAGER_ID,
            colleague_requester_id=DEMO_INTERN_ID,
            for_owner=True,
        )
        assert "sprint planner wiki" in block.lower()
        assert "handbook" in block.lower()
        assert "Context (derived)" in block
        memory.reset_memory()


def test_twin_session_refreshes_context_after_exchange():
    with _with_temp_db(turns="2"):
        memory.reset_memory()
        from agent_network.agent.twin_chat import TwinChatSession
        from agent_network.registry import DEMO_INTERN_ID, DEMO_MANAGER_ID

        intern = TwinChatSession(DEMO_MANAGER_ID, requester_employee_id=DEMO_INTERN_ID)
        intern.employee.is_absent = True
        with patch.dict(os.environ, {"AGENT_NETWORK_MODE": "mock", "LLM_PROVIDER": "none"}):
            intern.handle("blocked on LST-77777 database migration phase one")
            intern.handle("still stuck on migration rollback steps")

        conv = intern.conversation_id
        assert memory.history_count(conv) >= 4
        summary = context_memory.get_summary(conv)
        assert summary is not None
        assert "LST-77777" in summary or "migration" in summary.lower()
        memory.reset_memory()
