"""
Rule-based + optional LLM chat with a digital twin.

Maps natural-ish phrases to MCP tools: list, get, delegate, GitLab, owner controls.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from agent_network.agent.access_policy import (
    can_view_ticket,
    deny_delegate_from_colleague,
    deny_implement_mr,
    deny_list_twin_queue,
    deny_view_ticket,
    owner_is_direct_command,
    requester_is_twin_owner,
)
from agent_network import context_memory, memory, owner_instruction_memory
from agent_network.absence import absence_reason, is_effectively_absent
from agent_network.agent.conversational import (
    HUMAN_VOICE,
    answer_from_owner_rules,
    human_help_reply,
)
from agent_network.agent.intent_handlers import dispatch_chat, dispatch_coordination
from agent_network.agent.llm_router import is_llm_enabled, llm_backend_label, try_llm_agent_reply
from agent_network.agent.message_intent import classify_message
from agent_network.agent.work_actions import handle_work_request
from agent_network.agent.owner_intent import (
    apply_owner_instruction,
    is_delegate_activity_query,
    is_owner_activity_query,
    is_owner_instruction_message,
)
from agent_network.audit import (
    format_owner_activity_summary,
    format_owner_ticket_assignment_summary,
    log_twin_action,
    read_twin_audit,
)
from agent_network.config import is_mock_mode
from agent_network.mcp_server.tools_registry import call_tool
from agent_network.registry import (
    DEMO_ASSIGNEE_ID,
    DEMO_MANAGER_ID,
    employee_by_id,
    employee_display_name,
    set_employee_absent,
)
from agent_network.standin_policy import (
    add_absence_window,
    get_policy,
    policy_summary,
    set_instructions,
    update_policy_from_message,
)

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Live Jira keys (LST-46547) and mock keys (JIRA-A631BB56)
_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-[A-Z0-9]+)\b", re.IGNORECASE)
_MR_URL_RE = re.compile(r"https?://\S+")
_ASSIGNEE_ALIASES = {
    "assignee": DEMO_ASSIGNEE_ID,
    "demo assignee": DEMO_ASSIGNEE_ID,
    "engineer": DEMO_ASSIGNEE_ID,
}


def _stand_in_blocks_ticket_assignment(twin_employee_id: str, requester_employee_id: str) -> bool:
    """Colleagues only — owner direct commands are never blocked by stand-in policy."""
    from agent_network.ticket_approval import requires_ticket_approval

    if owner_is_direct_command(requester_employee_id, twin_employee_id):
        return False
    if not requester_employee_id or requester_employee_id == twin_employee_id:
        return False
    # Approval queue handles colleague ticket asks — do not hard-block before notify.
    if requires_ticket_approval(twin_employee_id):
        return False
    return not get_policy(twin_employee_id).can_delegate


def _assignment_blocked_message(owner_name: str) -> str:
    return (
        f"{owner_name} asked me not to assign or create tickets "
        f"while they're away — they'll handle assignment themselves."
    )


class TwinChatSession:
    """
    Human talks to an employee's twin.

    When the employee is absent, the twin stands in for colleagues.
    When the owner talks to their own twin, they configure absence and review activity.
    """

    def __init__(
        self,
        twin_employee_id: str,
        requester_employee_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        emp = employee_by_id(twin_employee_id)
        if not emp:
            raise ValueError(f"Unknown twin employee id: {twin_employee_id}")
        self.twin_employee_id = twin_employee_id
        self.employee = emp
        self.conversation_id = conversation_id or (
            f"{twin_employee_id}:{requester_employee_id or 'anon'}"
        )

        if requester_employee_id:
            requester = employee_by_id(requester_employee_id)
            if not requester:
                raise ValueError(f"Unknown requester employee id: {requester_employee_id}")
            self.requester_employee_id = requester_employee_id
            self.requester = requester
        else:
            self.requester_employee_id = None
            self.requester = None

    def is_owner_session(self) -> bool:
        return requester_is_twin_owner(self.requester_employee_id, self.twin_employee_id)

    def is_absent(self) -> bool:
        """Effective absence: manual flag, scheduled window, or Teams presence."""
        return is_effectively_absent(self.twin_employee_id)

    def memory_messages(self) -> list[dict]:
        """Recent verbatim chat turns for this thread only."""
        return memory.recent(self.conversation_id)

    def conversation_context_block(self) -> str:
        """Derived context for this thread (older turns folded into a summary)."""
        return context_memory.prompt_block(self.conversation_id)

    def owner_colleague_activity_context(
        self, colleague_requester_id: Optional[str] = None
    ) -> str:
        """Fetch one colleague's stand-in transcript (owner sessions only)."""
        if not self.is_owner_session():
            return ""
        return memory.colleague_activity_prompt_block(
            self.twin_employee_id,
            colleague_requester_id=colleague_requester_id,
            for_owner=True,
        )

    def fetch_colleague_conversations_for_owner(
        self, colleague_requester_id: Optional[str] = None
    ) -> str:
        """On-demand lookup when owner asks what a specific colleague said."""
        if not self.is_owner_session():
            return (
                "Access denied: only the twin owner can request colleague "
                "conversation transcripts."
            )
        if not colleague_requester_id:
            names = memory.colleagues_with_conversations(self.twin_employee_id)
            if not names:
                return "No colleague stand-in conversations recorded yet."
            who = ", ".join(name for _, name in names)
            return (
                "Which colleague do you mean? I have stand-in chats with: "
                f"{who}. Ask e.g. 'what did the intern say?'"
            )
        ctx = self.owner_colleague_activity_context(colleague_requester_id)
        return ctx or "No transcript found for that colleague."

    def _remember(self, role: str, content: str) -> None:
        memory.remember(self.conversation_id, role, content, self.twin_employee_id)

    def llm_system_prompt(self) -> str:
        owner = self.is_owner_session()
        mode = "owner coordination" if owner else "colleague stand-in"
        absent = "absent" if self.is_absent() else "present"
        policy = get_policy(self.twin_employee_id)
        requester = self.requester.name if self.requester else "a colleague"
        prompt = (
            f"You are the digital twin of {self.employee.name} at Sprinklr. "
            f"They are currently {absent} ({absence_reason(self.twin_employee_id)}).\n"
            f"Session mode: {mode}. You are talking to: {requester}.\n"
            f"Stand-in policy: can_delegate={'yes' if policy.can_delegate else 'no'}, "
            f"notify_on_delegate={'yes' if policy.notify_on_delegate else 'no'}, "
            f"require_ticket_approval={'yes' if policy.require_ticket_approval else 'no'}, "
            f"default delegate target={employee_display_name(policy.default_delegate_to) if policy.default_delegate_to else 'assignee'}.\n"
        )
        owner_ctx = owner_instruction_memory.prompt_block(
            self.twin_employee_id, self.employee.name
        )
        if owner_ctx:
            prompt += f"\n{owner_ctx}\n"
        thread_ctx = self.conversation_context_block()
        if thread_ctx:
            prompt += f"\n{thread_ctx}\n"
        if owner:
            prompt += (
                "\nOwner coordination: colleague stand-in transcripts are NOT loaded "
                "automatically — they are fetched when the owner asks what someone "
                "said or about stand-in conversations. Quote fetched transcripts "
                "accurately; never invent dialogue.\n"
            )
        prompt += (
            HUMAN_VOICE
            + "\n\nTechnical rules (follow silently, don't recite to user):\n"
            "- Only use Jira/GitLab/delegate tools when they clearly need live data or a concrete action.\n"
            "- NEVER invent ticket IDs — only use IDs from tool results or this conversation.\n"
            "- Help colleagues with THEIR blocker; do not expose the owner's full backlog.\n"
            "- Only delegate when explicitly requested and owner is absent.\n"
            "- If require_ticket_approval=yes: NEVER create tickets for colleagues yourself. "
            "Queue TA-XXX, notify owner on Teams, and wait for approve TA-X.\n"
            "- NEVER claim you notified the owner unless a TA reference was queued.\n"
            "- NEVER print JSON tool calls. Invoke tools via the API only.\n"
            f"- Reporter for delegation is always the twin owner ({self.employee.employee_id})."
        )
        return prompt

    def greeting(self) -> str:
        requester = self.requester.name if self.requester else None
        owner = self.employee.name

        if self.is_owner_session():
            if self.is_absent():
                return (
                    f"Hey — I'm your stand-in while you're away. "
                    "What should I know before colleagues start pinging me?"
                )
            return (
                "Hey. I'm your coordination twin — "
                "absence setup, tickets, whatever you need."
            )

        if self.is_absent():
            hi = f"Hey {requester}! " if requester else "Hey! "
            return (
                f"{hi}I'm covering for {owner} while they're away. "
                "What's going on?"
            )

        hi = f"Hey {requester} — " if requester else "Hey — "
        return f"{hi}{owner} is around. How can I help?"

    def handle(self, user_message: str) -> str:
        text = user_message.strip()
        if not text:
            return "Say something — e.g. 'list my tickets' or 'help'."
        reply = self._route(text)
        self._remember("user", text)
        self._remember("assistant", reply)
        context_memory.refresh_from_chat(self.conversation_id, self.twin_employee_id)
        if self.is_owner_session():
            owner_instruction_memory.process_owner_message(
                self.twin_employee_id, text, reply
            )
        return reply

    def _route(self, text: str) -> str:
        lower = text.lower()
        if lower in {"help", "?", "commands"}:
            return human_help_reply(self, text)

        intent = classify_message(self, text)

        # 1) Owner coordination: policy mutations, introspection (LLM-first), help
        coord = dispatch_coordination(self, text, intent)
        if coord is not None:
            return coord

        if self.is_owner_session():
            owner_reply = self._handle_owner_commands(text, lower)
            if owner_reply:
                return owner_reply

        # Colleague ticket requests with owner approval policy — deterministic, before LLM.
        if (
            not self.is_owner_session()
            and self.requester_employee_id
            and self.requester_employee_id != self.twin_employee_id
        ):
            from agent_network.agent.llm_tool_guards import user_wants_create_ticket_for_self
            from agent_network.ticket_approval import requires_ticket_approval

            if requires_ticket_approval(self.twin_employee_id) and user_wants_create_ticket_for_self(
                text
            ):
                return self._create_ticket_for_requester(text)

        # 2) LLM agent — model decides tools vs chat vs audit/memory fetch
        if is_llm_enabled():
            agent_reply = try_llm_agent_reply(self, text, intent=intent)
            if agent_reply:
                return agent_reply

        # 3) Deterministic work actions (keyword router when LLM off)
        work_reply = handle_work_request(self, text)
        if work_reply:
            return work_reply

        # 4) Owner standing rules — deterministic when LLM missed or failed
        rule_reply = answer_from_owner_rules(self, text)
        if rule_reply:
            return rule_reply

        # 5) Pure conversation fallback
        return dispatch_chat(self, text)

    def _handle_owner_commands(self, text: str, lower: str) -> Optional[str]:
        from agent_network.ticket_approval import (
            approve_pending,
            format_pending_list,
            list_pending,
            parse_owner_approval_message,
            reject_pending,
        )

        if any(
            p in lower
            for p in (
                "pending approval",
                "pending ticket",
                "approval queue",
                "waiting for approval",
            )
        ):
            return format_pending_list(self.twin_employee_id)

        action, ref = parse_owner_approval_message(text)
        if action in ("approve", "reject"):
            if not ref:
                pending = list_pending(self.twin_employee_id)
                if len(pending) == 1:
                    ref = pending[0]["ref_code"]
                elif not pending:
                    return "No pending ticket approvals right now."
                else:
                    return (
                        f"{format_pending_list(self.twin_employee_id)}\n"
                        "Which one? e.g. approve TA-1"
                    )
            if action == "approve":
                result = approve_pending(ref, self.twin_employee_id)
            else:
                result = reject_pending(ref, self.twin_employee_id)
            if not result.get("success"):
                return result.get("detail", "Could not process that approval.")
            if action == "approve":
                tid = result.get("ticket_id", "")
                who = result.get("requester_name", "colleague")
                title = result.get("title", "")
                return (
                    f"Approved **{ref}** — created **{tid}** for {who}: {title}. "
                    "They can check their Jira board."
                )
            who = result.get("requester_name", "colleague")
            return f"Declined **{ref}** — I won't create a ticket for {who}."

        if any(p in lower for p in ("go absent", "mark absent", "i'm ooo", "im ooo", "going absent")):
            set_employee_absent(self.twin_employee_id, True)
            log_twin_action(
                twin_employee_id=self.twin_employee_id,
                action="owner_go_absent",
                detail="owner marked absent via chat",
                data={"requester_id": self.requester_employee_id},
            )
            return (
                f"You're now marked **absent**. Your twin will stand in for colleagues.\n\n"
                f"{policy_summary(self.twin_employee_id)}"
            )

        if any(p in lower for p in ("go present", "mark present", "i'm back", "im back")):
            set_employee_absent(self.twin_employee_id, False)
            log_twin_action(
                twin_employee_id=self.twin_employee_id,
                action="owner_go_present",
                detail="owner marked present via chat",
                data={"requester_id": self.requester_employee_id},
            )
            return "Welcome back — you're marked **present**. Stand-in mode is off."

        if any(
            p in lower
            for p in (
                "stand-in settings",
                "stand-in policy",
                "stand in settings",
                "show stand-in",
            )
        ):
            return policy_summary(self.twin_employee_id)

        if lower.startswith("instructions:") or (
            is_owner_instruction_message(lower) and not is_owner_activity_query(lower)
        ):
            if lower.startswith("instructions:"):
                instr = text.split(":", 1)[1].strip()
            else:
                instr = text.strip()
            if instr:
                reply = apply_owner_instruction(self.twin_employee_id, text, lower)
                log_twin_action(
                    twin_employee_id=self.twin_employee_id,
                    action="owner_set_instructions",
                    detail=instr[:200],
                    data={"requester_id": self.requester_employee_id},
                )
                return reply
            return "Tell me how to act, e.g. 'instructions: only delegate P0 issues to assignee'."

        if "absent from" in lower:
            dates = _DATE_RE.findall(text)
            if len(dates) >= 2:
                try:
                    start = datetime.fromisoformat(dates[0]).replace(tzinfo=timezone.utc)
                    end = datetime.fromisoformat(dates[1]).replace(tzinfo=timezone.utc)
                except ValueError:
                    return "Use ISO dates, e.g. 'absent from 2026-07-01 to 2026-07-03'."
                window = add_absence_window(self.twin_employee_id, start, end)
                log_twin_action(
                    twin_employee_id=self.twin_employee_id,
                    action="owner_set_absence_window",
                    detail=window,
                    data={"requester_id": self.requester_employee_id},
                )
                return (
                    f"Scheduled: I'll stand in for you {window}. "
                    "You don't need to mark yourself absent manually for that period."
                )
            return "Use ISO dates, e.g. 'absent from 2026-07-01 to 2026-07-03'."

        if "stand-in rules" in lower or "stand in rules" in lower:
            updated = update_policy_from_message(self.twin_employee_id, lower)
            if updated:
                return f"Updated.\n\n{updated}"
            return (
                "Tell me rules, e.g.:\n"
                "  • stand-in rules: notify me on delegate\n"
                "  • stand-in rules: no delegate\n"
                "  • stand-in rules: notify off"
            )

        if is_owner_activity_query(lower):
            return self._absence_summary() if not is_delegate_activity_query(lower) else self._delegate_activity_summary()

        return None

    def _delegate_activity_summary(self) -> str:
        return format_owner_ticket_assignment_summary(self.twin_employee_id)

    def _absence_summary(self) -> str:
        if not self.is_owner_session():
            return "Activity summaries are only available to the twin owner."
        colleague_ctx = memory.colleagues_activity_summary(self.twin_employee_id)
        return format_owner_activity_summary(
            self.twin_employee_id,
            colleague_summary=colleague_ctx,
        )

    def _help_text(self) -> str:
        return human_help_reply(self)

    @staticmethod
    def _is_list_intent(lower: str) -> bool:
        from agent_network.agent.action_reasoning import user_wants_list_tickets

        return user_wants_list_tickets(lower)

    @staticmethod
    def _is_gitlab_list_intent(lower: str) -> bool:
        from agent_network.agent.action_reasoning import user_wants_list_merge_requests

        return user_wants_list_merge_requests(lower)

    @staticmethod
    def _is_gitlab_link_intent(lower: str) -> bool:
        from agent_network.agent.action_reasoning import user_wants_link_mr

        return user_wants_link_mr(lower)

    @staticmethod
    def _is_get_intent(lower: str) -> bool:
        from agent_network.agent.action_reasoning import user_wants_ticket_status

        return user_wants_ticket_status(lower)

    @staticmethod
    def _is_delegate_intent(text: str) -> bool:
        from agent_network.agent.llm_tool_guards import user_wants_delegate

        return user_wants_delegate(text)

    def _extract_create_title(self, text: str) -> Optional[str]:
        from agent_network.agent.ticket_title import extract_ticket_title_from_request

        return extract_ticket_title_from_request(text)

    def _create_ticket_for_requester(self, text: str) -> str:
        if not self.requester_employee_id:
            return "Who should I assign this to?"
        if _stand_in_blocks_ticket_assignment(
            self.twin_employee_id, self.requester_employee_id
        ):
            return _assignment_blocked_message(self.employee.name)
        if not self.is_absent() and not self.is_owner_session():
            return (
                f"{self.employee.name} isn't marked absent right now, "
                "so I can't file stand-in tickets yet."
            )
        title = self._extract_create_title(text)
        if not title:
            return "What should I call it? e.g. 'Sprint Planner' or 'onboarding handbook'."

        from agent_network.ticket_approval import (
            colleague_pending_message,
            find_open_for_requester,
            requires_ticket_approval,
        )

        if (
            not self.is_owner_session()
            and self.requester_employee_id != self.twin_employee_id
            and requires_ticket_approval(self.twin_employee_id)
        ):
            return colleague_pending_message(
                twin_employee_id=self.twin_employee_id,
                requester_employee_id=self.requester_employee_id,
                conversation_id=self.conversation_id,
                title=title,
                owner_name=self.employee.name,
            )

        existing = find_open_for_requester(
            self.twin_employee_id, self.requester_employee_id, title
        )
        if existing and existing["status"] == "approved" and existing.get("ticket_id"):
            return (
                f"Your manager already approved this — ticket **{existing['ticket_id']}** "
                f"is on your board: {existing['title']}."
            )

        result = call_tool(
            "twin_create_ticket_for_requester",
            {
                "twin_employee_id": self.twin_employee_id,
                "requester_employee_id": self.requester_employee_id,
                "title": title,
                "description": "",
            },
        )
        if result.get("isError"):
            return result["content"][0]["text"]
        data = json.loads(result["content"][0]["text"])
        tid = data.get("ticket_id", "")
        return (
            f"Done — I created **{tid}** for you: {data.get('title', title)}. "
            "You should see it on your tickets now."
        )

    @staticmethod
    def _extract_ticket_id(text: str) -> Optional[str]:
        m = _TICKET_RE.search(text)
        return m.group(1).upper() if m else None

    def _list_scope(self, lower: str) -> str:
        if any(p in lower for p in ("your ticket", "your tickets", "their ticket", "manager ticket")):
            return "twin"
        if "my ticket" in lower:
            return "requester"
        if self.requester:
            return "requester"
        return "twin"

    def _list_email_for_scope(self, scope: str) -> Optional[str]:
        if scope == "requester" and self.requester:
            return self.requester.email
        if scope == "twin":
            return self.employee.email
        return None

    def _resolve_assignee(self, lower: str) -> str:
        for alias, emp_id in _ASSIGNEE_ALIASES.items():
            if alias in lower:
                return emp_id
        policy = get_policy(self.twin_employee_id)
        if policy.default_delegate_to:
            return policy.default_delegate_to
        return DEMO_ASSIGNEE_ID

    def _delegate(self, text: str, lower: str) -> str:
        denied = deny_delegate_from_colleague(
            self.requester_employee_id, self.twin_employee_id
        )
        if denied:
            return denied
        owner_command = owner_is_direct_command(
            self.requester_employee_id, self.twin_employee_id
        )
        if not owner_command and not self.is_absent():
            return (
                f"{self.employee.name} is actually around right now — "
                "they can handle things directly. I only route work when they're marked absent."
            )

        policy = get_policy(self.twin_employee_id)
        if not owner_command and not policy.can_delegate:
            return _assignment_blocked_message(self.employee.name)

        assignee_id = self._resolve_assignee(lower)
        title = self._extract_delegate_title(text)
        if not title:
            return (
                "What should I route, and to who? "
                "Just describe the work — like 'hand off the handbook fix to the assignee'."
            )

        requester_note = ""
        if self.requester:
            requester_note = f" (requested by {self.requester.name})"

        result = call_tool(
            "twin_delegate_ticket",
            {
                "reporter_employee_id": self.twin_employee_id,
                "invoker_employee_id": self.requester_employee_id,
                "assignee_employee_id": assignee_id,
                "title": title,
                "description": f"Delegated via twin chat{requester_note}: {title}",
            },
        )
        return self._format_tool_result(
            result,
            ok_summary=(
                f"Done — I delegated '{title}' to "
                f"{employee_display_name(assignee_id)}'s twin via the agent bus."
            ),
        )

    @staticmethod
    def _extract_delegate_title(text: str) -> str:
        lower = text.lower()
        assign_about = re.search(
            r"assign\s+(?:the\s+)?(?:demo\s+)?(?:assignee|intern|engineer|\w+)\s+"
            r"a\s+ticket\s+(?:about|for|on)\s+(.+?)(?:\s+then\b|[.!]\s*$|$)",
            text,
            re.I,
        )
        if assign_about:
            title = assign_about.group(1).strip().rstrip(".")
            if title.lower().endswith(" do it"):
                title = title[:-6].strip()
            if title:
                return title
        for prefix in ("delegate ", "assign ticket ", "assign "):
            if lower.startswith(prefix):
                rest = text[len(prefix) :].strip()
                for suffix in (" to assignee", " to demo assignee", " to engineer"):
                    if rest.lower().endswith(suffix):
                        rest = rest[: -len(suffix)].strip()
                if rest:
                    return rest
        if "delegate" in lower:
            _, _, rest = text.partition("delegate")
            rest = rest.strip()
            for sep in (" to assignee", " to demo assignee", " to engineer"):
                if rest.lower().endswith(sep):
                    rest = rest[: -len(sep)].strip()
            return rest
        return ""

    def _list_merge_requests(self, lower: str) -> str:
        state = "merged" if "merged" in lower else "opened"
        result = call_tool("gitlab_list_merge_requests", {"state": state, "limit": 10})
        if result.get("isError"):
            return result["content"][0]["text"]
        items = json.loads(result["content"][0]["text"])
        if not items:
            return f"No {state} merge requests found."
        lines = [
            f"!{mr.get('iid')} | {mr.get('state')} | {str(mr.get('title', ''))[:45]}"
            for mr in items
        ]
        log_twin_action(
            twin_employee_id=self.twin_employee_id,
            action="gitlab_list_merge_requests",
            detail=f"listed {len(items)} MRs",
            data={"requester_id": self.requester_employee_id},
        )
        return f"Found {len(items)} merge request(s):\n" + "\n".join(
            f"  • {ln}" for ln in lines
        )

    def _link_mr_to_ticket(self, text: str, lower: str) -> str:
        ticket_id = self._extract_ticket_id(text)
        url_match = _MR_URL_RE.search(text)
        if not ticket_id or not url_match:
            return "Usage: link MR https://gitlab.../merge_requests/N to TICKET-ID"
        mr_url = url_match.group(0).rstrip(").,]")
        result = call_tool(
            "gitlab_link_mr_to_ticket",
            {"ticket_id": ticket_id, "mr_url": mr_url},
        )
        return self._format_tool_result(
            result,
            ok_summary=f"Linked MR to {ticket_id}.",
        )

    def _implement_ticket_mr(self, text: str) -> str:
        ticket_id = self._extract_ticket_id(text)
        if not ticket_id:
            return "Usage: implement TICKET-ID (e.g. implement LST-12345)"
        denied = deny_implement_mr(self.requester_employee_id, self.twin_employee_id)
        if denied:
            return denied
        result = call_tool(
            "gitlab_create_mr_from_ticket",
            {"ticket_id": ticket_id},
        )
        log_twin_action(
            twin_employee_id=self.twin_employee_id,
            action="gitlab_create_mr_from_ticket",
            detail=f"sub-agent MR for {ticket_id}",
            data={"requester_id": self.requester_employee_id, "ticket_id": ticket_id},
        )
        return self._format_tool_result(
            result,
            ok_summary=f"Opened GitLab MR for {ticket_id}.",
        )

    def _list_tickets(self, lower: str) -> str:
        scope = self._list_scope(lower)

        denied = deny_list_twin_queue(
            self.requester_employee_id, self.twin_employee_id, scope
        )
        if denied:
            log_twin_action(
                twin_employee_id=self.twin_employee_id,
                action="jira_list_tickets_denied",
                detail="blocked twin queue browse",
                data={"requester_id": self.requester_employee_id, "scope": scope},
            )
            return denied

        email = self._list_email_for_scope(scope)

        args: dict[str, Any] = {}
        if email:
            args["assignee_email"] = email

        result = call_tool("jira_list_tickets", args)
        if result.get("isError"):
            return result["content"][0]["text"]
        items = json.loads(result["content"][0]["text"])

        if not items and is_mock_mode() and scope == "requester" and not self.requester:
            return (
                "No matching tickets found. Set --as emp-intern (or pick 'You are' in Streamlit) "
                "so 'my tickets' knows who you are."
            )

        label = {
            "requester": f"{self.requester.name}'s" if self.requester else "your",
            "twin": f"{self.employee.name}'s",
        }.get(scope, "matching")

        if not items:
            return f"No {label} tickets found."

        lines = [f"{i['ticket_id']} | {i['status']} | {i['title'][:50]}" for i in items]
        log_twin_action(
            twin_employee_id=self.twin_employee_id,
            action="jira_list_tickets",
            detail=f"listed tickets via chat (scope={scope})",
            data={"count": len(items), "requester_id": self.requester_employee_id},
        )
        return f"Here are {len(items)} {label} ticket(s):\n" + "\n".join(
            f"  • {ln}" for ln in lines
        )

    def _get_ticket(self, ticket_id: str) -> str:
        result = call_tool("jira_get_ticket", {"ticket_id": ticket_id})
        if result.get("isError"):
            return result["content"][0]["text"]
        data = json.loads(result["content"][0]["text"])

        if not can_view_ticket(self.requester_employee_id, self.twin_employee_id, data):
            denied = deny_view_ticket(
                self.requester_employee_id, self.twin_employee_id, ticket_id
            )
            log_twin_action(
                twin_employee_id=self.twin_employee_id,
                action="jira_get_ticket_denied",
                detail=ticket_id,
                data={"requester_id": self.requester_employee_id},
            )
            return denied or "You don't have access to that ticket."

        log_twin_action(
            twin_employee_id=self.twin_employee_id,
            action="jira_get_ticket",
            detail=ticket_id,
            data={"requester_id": self.requester_employee_id},
        )
        lines = [
            f"Ticket {data['ticket_id']}",
            f"  Title: {data['title']}",
            f"  Status: {data['status']}",
            f"  Assignee: {data.get('assignee_id') or 'unassigned'}",
        ]
        description = (data.get("description") or "").strip()
        if description:
            lines.append(f"  Description: {description[:500]}")
        comments = data.get("comments") or []
        if comments:
            lines.append("  Comments:")
            for comment in comments:
                author = comment.get("author", "unknown")
                created = comment.get("created", "")
                text = str(comment.get("text", "")).strip().replace("\n", " ")
                prefix = f"    • {created} | {author}:" if created else f"    • {author}:"
                lines.append(f"{prefix} {text[:300]}")
        else:
            lines.append("  Comments: (none)")
        return "\n".join(lines)

    @staticmethod
    def _format_tool_result(result: dict[str, Any], ok_summary: str) -> str:
        if result.get("isError"):
            return result["content"][0]["text"]
        payload = json.loads(result["content"][0]["text"])
        if isinstance(payload, dict) and payload.get("success") is False:
            return payload.get("detail", "Action failed.")
        extra = ""
        if isinstance(payload, dict) and payload.get("owner_notification"):
            extra = f"\n  {payload['owner_notification']}"
        if isinstance(payload, dict) and payload.get("ticket_id"):
            return f"{ok_summary}\n  Ticket: {payload['ticket_id']}{extra}"
        return f"{ok_summary}{extra}"
