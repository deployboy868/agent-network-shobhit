"""Streamlit Cloud / Render entrypoint — keeps PYTHONPATH correct."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _bootstrap_streamlit_secrets() -> None:
    """Map Streamlit Cloud secrets → os.environ before app imports config."""
    try:
        import streamlit as st

        for key, value in st.secrets.items():
            if isinstance(value, str):
                os.environ.setdefault(key, value)
    except Exception:
        pass


_bootstrap_streamlit_secrets()

from agent_network.demo.twin_chat_app import main

if __name__ == "__main__":
    main()
