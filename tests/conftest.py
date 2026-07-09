"""Pytest hooks — keep unit tests fast and deterministic."""

from __future__ import annotations

import os

import pytest

# Real LLM calls (Ollama/Grok) make tests slow and non-deterministic.
os.environ["LLM_PROVIDER"] = "none"
os.environ["OLLAMA_ENABLED"] = ""


@pytest.fixture(autouse=True)
def _isolated_standin_policies():
    from agent_network.standin_policy import reset_standin_policies

    reset_standin_policies()
    yield
    reset_standin_policies()
