"""Tests for per-conversation memory store."""

import os
import tempfile
from unittest.mock import patch

from agent_network import memory


def _with_temp_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return tmp.name


def test_memory_remember_and_recent():
    db = _with_temp_db()
    with patch.dict(os.environ, {"TWIN_MEMORY_DB": db, "TWIN_MEMORY_TURNS": "10"}):
        memory.reset_memory()
        conv = "conv-1"
        memory.remember(conv, "user", "list my tickets", "emp-manager")
        memory.remember(conv, "assistant", "Here are 2 tickets", "emp-manager")
        memory.remember(conv, "user", "delegate the first one", "emp-manager")

        turns = memory.recent(conv)
        assert len(turns) == 3
        assert turns[0] == {"role": "user", "content": "list my tickets"}
        assert turns[-1]["content"] == "delegate the first one"
        assert memory.history_count(conv) == 3
        memory.reset_memory()


def test_memory_isolated_per_conversation():
    db = _with_temp_db()
    with patch.dict(os.environ, {"TWIN_MEMORY_DB": db}):
        memory.reset_memory()
        memory.remember("a", "user", "hi from a")
        memory.remember("b", "user", "hi from b")
        assert len(memory.recent("a")) == 1
        assert memory.recent("a")[0]["content"] == "hi from a"
        assert len(memory.recent("b")) == 1
        memory.clear("a")
        assert memory.recent("a") == []
        assert len(memory.recent("b")) == 1
        memory.reset_memory()
