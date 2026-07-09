"""Human-sounding conversational replies (LLM prompt + offline fallback)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

from agent_network.config import is_llm_enabled

if TYPE_CHECKING:
    from agent_network.agent.twin_chat import TwinChatSession

_GREETING = re.compile(
    r"\b(hi|hello|hey|hiya|good morning|good afternoon|good evening|yo|sup)\b", re.I
)
_VAGUE_HELP = re.compile(
    r"\b(i need help|need help|can you help|could you help|help me|stuck|blocked|having trouble)\b",
    re.I,
)
_THANKS = re.compile(r"\b(thanks|thank you|thx|appreciate it|cheers)\b", re.I)
_REAL_QUESTION = re.compile(
    r"(\?|^(what|where|how|when|why|can you|could you|tell me|is there|do you know)\b)",
    re.I,
)

HUMAN_VOICE = """
How to think and talk:
- You ARE this person's twin — a real teammate, not a bot reading a manual.
- DEFAULT: talk first. Only Jira/GitLab/delegate actions happen when the user clearly asks.
- Your owner may have briefed you on how to handle colleagues, tone, and specific topics — follow that in every chat, not only when they are in the room.
- When they describe work ("my manager assigned me X") without asking you to act, empathize and offer help — do NOT list tickets or invent ticket IDs.
- When the user asks you to DO something (create ticket, list, delegate), the system runs the tool FIRST.
- Your job after an action: explain what happened naturally, using the real results provided.
- Your job when no action is needed: talk like a teammate, ask what's blocking them.
- Write like Slack/Teams: short paragraphs, contractions OK, no bullet dumps unless listing real data (tickets, MRs).
- Explain capabilities in plain English ("I can check your Jira tickets") — never paste command syntax unless they ask for exact wording.
- Use ONLY the real names given in the roster below — never invent people (no Ana, Sarah, etc.).
- One clarifying question beats a wall of options.
- Never say "Commands:", "Stand-in note:", or dump system/policy text raw.
"""


def is_explicit_help_request(message: str) -> bool:
    """True when the user wants to know what the twin can do — not 'I need help'."""
    lower = message.lower().strip()
    if lower in {"help", "?", "commands"}:
        return True
    return lower in {
        "what can you do",
        "what can you do?",
        "what do you do",
        "what do you do?",
        "show commands",
        "show me commands",
        "list commands",
        "how can you help",
        "how can you help?",
    }


def conversational_system_prompt(session: "TwinChatSession") -> str:
    owner_name = session.employee.name
    requester = session.requester.name if session.requester else "a colleague"
    owner_session = session.is_owner_session()
    absent = session.is_absent()

    if owner_session:
        role = (
            f"You are {owner_name}'s coordination twin at Sprinklr. "
            f"{owner_name} is messaging you about their own absence, tickets, and stand-in rules."
        )
    elif absent:
        role = (
            f"You are covering for {owner_name} while they are away. "
            f"{requester} is a colleague who came to you for help — treat them the way {owner_name} would."
        )
    else:
        role = (
            f"You are {owner_name}'s twin. {owner_name} is available; "
            f"{requester} reached out to you."
        )

    roster = (
        "People in this session (ONLY these names exist — never invent others):\n"
        f"  • Person you stand in for: {owner_name}\n"
        f"  • Person you are talking to: {requester}\n"
        "  • Others in demo: Demo Assignee, Demo Observer\n"
    )

    from agent_network.owner_instruction_memory import prompt_block

    owner_ctx = prompt_block(session.twin_employee_id, owner_name)
    block = f"{role}\n{roster}\n{HUMAN_VOICE}\n"
    if owner_ctx:
        block += f"\n{owner_ctx}\n"
    thread_ctx = session.conversation_context_block()
    if thread_ctx:
        block += f"\n{thread_ctx}\n"
    if owner_session:
        block += (
            "\nYou are speaking with the owner. Colleague chat transcripts are loaded "
            "on demand when they ask what someone said — use provided facts exactly; "
            "never share one colleague's thread with another.\n"
        )
    block += f"When someone is away, say '{owner_name}' is out — not any other name."
    return block


def capabilities_context(session: "TwinChatSession") -> str:
    """Factual capabilities for the LLM to explain in human language."""
    owner = session.employee.name
    lines: list[str] = []

    if session.is_owner_session():
        lines.extend(
            [
                f"Talking to: {owner} (the twin owner).",
                "Can do: mark absent/present; save instructions for how to act while away;",
                "show or update stand-in rules (delegation, Teams notify);",
                "delegate work to teammates while absent;",
                "summarize what the twin did during absence;",
                "look up owner's Jira tickets and GitLab merge requests;",
                "implement a Jira ticket (open GitLab MR) when this twin has GitLab access.",
            ]
        )
    elif session.is_absent():
        requester = session.requester.name if session.requester else "colleague"
        lines.extend(
            [
                f"Talking to: {requester}. Standing in for {owner} who is away.",
                f"Can do for {requester}: check their Jira tickets; look up a ticket by ID;",
                "create a Jira ticket assigned to them (their work, on their board);",
                "list open GitLab MRs; link an MR to a ticket;",
                f"Cannot delegate work to others — only {owner} can route tasks.",
                f"Cannot share {owner}'s private full backlog with colleagues.",
            ]
        )
    else:
        lines.append(f"{owner} is present. Limited stand-in — mostly informational.")

    from agent_network.owner_instruction_memory import prompt_block
    from agent_network.standin_policy import get_policy

    policy = get_policy(session.twin_employee_id)
    owner_ctx = prompt_block(session.twin_employee_id, session.employee.name)
    if owner_ctx:
        lines.append(owner_ctx)
    elif policy.instructions:
        lines.append(f"Owner's standing instructions: {policy.instructions}")
    lines.append(
        f"Delegation allowed: {'yes' if policy.can_delegate else 'no'}."
    )
    return "\n".join(lines)


def human_help_reply(session: "TwinChatSession", user_message: str = "help") -> str:
    """Explain what the twin can do — always in human language."""
    from agent_network.config import is_llm_enabled

    facts = capabilities_context(session)
    if is_llm_enabled():
        from agent_network.agent.llm_router import try_llm_chat_reply

        reply = try_llm_chat_reply(
            session,
            user_message,
            context_facts=(
                f"The user wants to know what you can help with. "
                f"Explain naturally in 2-4 sentences, then optionally one short follow-up question.\n\n"
                f"{facts}"
            ),
        )
        if reply:
            return reply
    return _human_help_fallback(session)


def explain_work_result(
    session: "TwinChatSession",
    user_message: str,
    facts: str,
    *,
    action_hint: str = "",
) -> str:
    """After a tool runs: explain in human language but keep real IDs/data."""
    if not facts or not facts.strip():
        return conversational_fallback(session, user_message)

    instruction = (
        "You just took a real action. Explain what happened in 1-3 natural sentences. "
        "MUST keep exact ticket IDs (JIRA-...), counts, and names from the facts — never invent. "
        "Do not say you 'will' do something — it is already done (or say honestly if it failed)."
    )
    if action_hint:
        instruction += f" {action_hint}"

    if is_llm_enabled():
        reply = polish_reply(session, user_message, facts, instruction=instruction)
        if reply and "JIRA-" in facts.upper() and "JIRA-" not in reply.upper():
            for line in facts.splitlines():
                if "JIRA-" in line.upper():
                    return f"{reply}\n\n{line.strip()}"
        return reply or facts
    return facts


def polish_reply(
    session: "TwinChatSession",
    user_message: str,
    facts: str,
    *,
    instruction: str = "",
) -> str:
    """Turn system facts into a natural reply; fall back to a short human paraphrase."""
    from agent_network.config import is_llm_enabled

    if is_llm_enabled():
        from agent_network.agent.llm_router import try_llm_chat_reply

        extra = f"\n\nTask: {instruction}" if instruction else ""
        reply = try_llm_chat_reply(
            session,
            user_message,
            context_facts=f"{facts}{extra}",
        )
        if reply:
            return reply
    return _humanize_facts(facts)


def answer_from_owner_rules(
    session: "TwinChatSession", user_message: str
) -> Optional[str]:
    """
    When the LLM is down or missed the point, answer from owner standing rules.
    Critical for demo: colleague asks about Copilot/myaccess/etc.
    """
    from agent_network.owner_instruction_memory import (
        format_rule_answer_for_colleague,
        match_rules_for_colleague_question,
    )

    text = (user_message or "").strip()
    if not text:
        return None

    rules = match_rules_for_colleague_question(session.twin_employee_id, text)
    if not rules:
        return None

    owner = session.employee.name
    facts = format_rule_answer_for_colleague(owner, rules[0]["rule_text"])
    if is_llm_enabled():
        reply = polish_reply(
            session,
            user_message,
            facts,
            instruction=(
                "Answer the colleague's question directly using ONLY this owner guidance. "
                "Do not deflect with 'what are you working on'."
            ),
        )
        if reply:
            return reply
    return facts


def conversational_fallback(session: "TwinChatSession", user_message: str) -> str:
    """Natural reply when the LLM is off or slow."""
    requester = session.requester.name if session.requester else "there"
    owner = session.employee.name
    text = user_message.strip()

    if _THANKS.search(text):
        return "Anytime — ping me if anything else comes up."

    if _GREETING.search(text):
        if session.is_owner_session():
            if session.is_absent():
                return (
                    f"Hey {requester}. I'm on stand-in duty — "
                    "what should I keep an eye on while you're out?"
                )
            return (
                f"Hey {requester}. What do you need — "
                "setting up absence, checking tickets, something else?"
            )
        if session.is_absent():
            return (
                f"Hey {requester}! I'm covering for {owner} while they're away. "
                "What's going on?"
            )
        return f"Hey {requester}! {owner} is around — how can I help?"

    if _VAGUE_HELP.search(text):
        if session.is_owner_session():
            return (
                "Of course. What's on your mind — "
                "getting ready to be out of office, checking tickets, or something else?"
            )
        return (
            f"Happy to help. What's blocking you — "
            "a ticket you're waiting on, code review, or something you need routed?"
        )

    if is_explicit_help_request(text):
        return human_help_reply(session, text)

    rule_answer = answer_from_owner_rules(session, text)
    if rule_answer:
        return rule_answer

    if session.is_owner_session():
        return (
            "I'm here. Tell me what you need — "
            "absence setup, what happened while you were away, tickets, whatever."
        )

    if _REAL_QUESTION.search(text):
        return _human_help_fallback(session)

    return (
        f"I'm here for you while {owner} is out. "
        "What are you working on?"
    )


def _human_help_fallback(session: "TwinChatSession") -> str:
    owner = session.employee.name
    requester = session.requester.name if session.requester else "you"

    if session.is_owner_session():
        return (
            f"Hey {requester} — I'm your stand-in setup buddy. I can mark you absent or back, "
            "remember how you want me to handle things while you're out, and tell you what I did "
            "when you get back. I can also pull up your Jira tickets or GitLab MRs. "
            "What are you trying to sort out?"
        )
    if session.is_absent():
        return (
            f"Hey — I'm filling in for {owner} right now. If something's stuck, I can look at "
            f"your tickets, check merge requests, or get work to the right person if that's "
            f"what {owner} would normally do. What's going on?"
        )
    return (
        f"{owner} is around, but I can still point you in the right direction. "
        "What's up?"
    )


def _humanize_facts(facts: str) -> str:
    """Last-resort cleanup of robotic fact strings."""
    text = facts.strip()
    if "Recent twin activity" in text:
        body = text.split(":", 1)[-1].strip()
        return f"Here's what I've been up to while you were away:{body}"
    if "Stand-in policy" in text:
        return f"Here's how I'm set up to stand in for you:\n{text}"
    return text
