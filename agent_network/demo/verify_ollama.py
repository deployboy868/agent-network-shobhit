"""Smoke-test Ollama connectivity for twin chat LLM."""

from __future__ import annotations

import sys

from agent_network.config import is_llm_enabled, llm_provider, ollama_model


def main() -> int:
    if not is_llm_enabled():
        print("LLM not enabled. Set OLLAMA_ENABLED=true in .env")
        return 1
    if llm_provider() != "ollama":
        print(f"LLM provider is {llm_provider()}, not ollama")
        return 1

    try:
        from agent_network.agent.llm_router import _make_client
    except ImportError as e:
        print(f"Missing dependency: {e}")
        return 1

    model = ollama_model()
    print(f"Testing Ollama model: {model}")
    client = _make_client()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: ollama ok"}],
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        print(f"Response: {text}")
        print("SUCCESS — Ollama is reachable.")
        return 0
    except Exception as e:
        print(f"FAILED: {e}")
        print("\nIs Ollama running? Try: ollama serve")
        print(f"Did you pull the model? Try: ollama pull {model}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
