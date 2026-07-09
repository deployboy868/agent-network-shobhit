"""
Streamlit Community Cloud entrypoint.

Must call main() at module level — Streamlit does not use if __name__ == "__main__".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SECRET_KEYS = (
    "GROQ_API_KEY",
    "GROQ_BASE_URL",
    "GROQ_MODEL",
    "LLM_PROVIDER",
    "AGENT_NETWORK_MODE",
    "TWIN_MEMORY_DB",
    "TWIN_AUDIT_LOG",
    "OPENAI_API_KEY",
    "GROK_API_KEY",
)


def _bootstrap_streamlit_secrets() -> None:
    """Map Streamlit Cloud secrets → os.environ before config imports."""
    try:
        import streamlit as st

        for key in _SECRET_KEYS:
            if key in st.secrets:
                os.environ.setdefault(key, str(st.secrets[key]))
    except Exception:
        pass


_bootstrap_streamlit_secrets()

from agent_network.demo.twin_chat_app import main

main()
