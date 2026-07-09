"""Smoke-test Groq API connectivity (OpenAI-compatible endpoint)."""

from __future__ import annotations

from agent_network.config import groq_model, is_llm_enabled, llm_provider


def main() -> int:
    if not is_llm_enabled():
        print("LLM disabled — set LLM_PROVIDER=groq and GROQ_API_KEY in .env")
        return 1
    if llm_provider() != "groq":
        print(f"LLM provider is {llm_provider()}, not groq")
        return 1

    try:
        from agent_network.agent.llm_router import _make_client
    except ImportError as e:
        print(f"Missing dependency: {e}")
        return 1

    model = groq_model()
    print(f"Testing Groq model: {model}")
    client = _make_client()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: groq-ok"}],
            temperature=0,
            max_tokens=16,
        )
        text = (response.choices[0].message.content or "").strip()
        print(f"Response: {text}")
        if "groq-ok" in text.lower():
            print("Groq wiring OK.")
            return 0
        print("Unexpected response — check GROQ_MODEL and API key.")
        return 1
    except Exception as e:
        print(f"Groq call failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
