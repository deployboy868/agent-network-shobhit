# Final Demo Script — Agent Social Network

**Duration:** 5–7 minutes (+ 2 min Q&A)  
**Default mode:** mock (reliable, no VPN)  
**Hero demo:** Streamlit human-to-twin chat

---

## Before you start (5 min)

```bash
cd "/Users/shobhit.raj/Downloads/Agent Network Project"
source .venv/bin/activate
PYTHONPATH=. pytest tests/ -q
AGENT_NETWORK_MODE=mock PYTHONPATH=. streamlit run agent_network/demo/twin_chat_app.py
```

Open in separate tabs/windows (optional backups):

- Copilot Studio → your agent → **Test** panel
- Terminal ready for LangGraph command

Record a screen capture as backup if live demo makes you nervous.

---

## Opening (30 seconds) — say this first

> "When someone is out sick or in meetings all day, teammates still get blocked on Jira work — they don't know who owns what or who to delegate to. Context gets lost across Jira, Teams, and GitLab.
>
> We built **digital twins** — one agent per employee with their skills and tool access. When someone is **absent**, colleagues message their twin. The twin can look up work, check status, and delegate — and twins also coordinate with each other without a human in the loop.
>
> I'll show both: human-to-twin chat, then agent-to-agent automation."

---

## Part 1 — Human-to-twin (3 min) ⭐ MAIN DEMO

### Setup (sidebar)

| Setting | Value |
|---------|--------|
| **You are** | Demo Intern |
| **Talking to twin of** | Demo Manager **(absent)** |

Point out: **Twin status: Absent — stand-in** and skills (Jira, GitLab, Teams).

### Chat script (type in order)

| # | You type | What to say while it runs |
|---|----------|---------------------------|
| 1 | *(read the greeting)* | "Manager is OOO. The twin introduces itself as a stand-in with the same tools and authority." |
| 2 | `list my tickets` | "Intern asks about their own work — not the manager's full private queue. The twin scopes the answer." |
| 3 | *(copy a ticket ID from the list)* `status JIRA-XXXXXX` | "Check status on a specific ticket through our MCP tool layer — same backend Cursor and future Copilot would use." |
| 4 | `delegate handbook fix to assignee` | "Twin creates a ticket and delegates via the agent bus to the assignee's twin. This is the stand-in acting on the manager's behalf." |

### If they ask about trust / privacy

> "We log twin actions to an audit file, and access policy limits what a colleague can see when they're not the ticket owner."

Optional: show `.twin-audit.jsonl` in the project folder after delegate.

---

## Part 2 — Agents without humans (1 min)

Switch to terminal (keep Streamlit open or minimize):

```bash
AGENT_NETWORK_MODE=mock PYTHONPATH=. python -m agent_network.demo.assign_and_track_graph
```

**Say:**

> "Same backend — when no human is chatting, twins still coordinate: create ticket → assign via agent bus → assignee completes → reporter tracks until done. This is LangGraph orchestrating the flow."

Scroll to: `Created ticket`, `Assignee marked done`, `Final ticket status`, `LangGraph demo complete`.

---

## Part 3 — Production path: Copilot (30–60 sec)

Open Copilot Studio **Test** panel.

| Type | Purpose |
|------|---------|
| `hello` | Stand-in greeting topic |
| `my manager is out, blocked on handbook` | Absent-colleague scenario |

**Say:**

> "In production, this conversation happens in Microsoft Teams via Copilot Studio. We built stand-in topics for the absent-manager scenario. Full generative AI and tool Actions need a Copilot Studio license — our Python MCP backend is ready to connect. Streamlit shows the real tool execution today."

Do **not** claim Copilot calls Jira today.

---

## Closing (30 seconds)

> "What we built: twin runtime, agent bus, MCP tool layer with live Jira in sandbox, human-to-twin chat, and LangGraph automation. What needs Sprinklr enablement: Copilot generative license, Teams publish, Workday roster, and per-user Jira auth. The architecture is designed so we don't re-build — we plug in the enterprise pieces."

---

## One slide (draw or paste)

```
Problem:  Colleague blocked when owner is absent
Solution: Digital twin stand-in + agent-to-agent coordination

Built ✅                          Needs IT 🔴
────────────────                  ────────────────
Twin per employee (demo roster)   Workday / HR CSV
MCP tools (Jira live in sandbox)  Copilot license + Actions
Human-to-twin chat (Streamlit)    Teams publish
Agent bus + LangGraph             Per-user Jira auth
Copilot Topics (stand-in narrative)
MCP server for Cursor
```

---

## If something breaks

| Problem | Fix |
|---------|-----|
| Streamlit won't start | `pip install streamlit` in `.venv` |
| Empty ticket list | Use mock mode: `AGENT_NETWORK_MODE=mock` |
| `status JIRA-...` fails | Run `list my tickets` first; copy exact ID from reply |
| Live Jira fails | Switch to mock — say "offline demo mode" |
| Copilot gives generic reply | Use exact trigger phrases: `hello`, `manager is out`, `blocked` |
| LangGraph error | Mock mode; if live, use safe mode tickets only |

**Rule:** Never apologize for 2 minutes. Say "I'll use the recorded backup" and move on.

---

## What NOT to lead with

- "It's just keyword matching" — say "deterministic demo router; LLM moves to Copilot"
- Jira create/assign only — that's the old story
- "Product is incomplete" — say "prototype with clear production path"
- Deep MCP protocol / stdio unless they ask

---

## Optional extras (only if asked)

| Ask | Show |
|-----|------|
| "Real Jira?" | Live Streamlit with safe mode + `[Agent-Network-TEST]` prefix |
| "Manager view?" | `PYTHONPATH=. python -m agent_network.demo.review_tasks` |
| "MCP / Cursor?" | Cursor calling agent-network MCP tools, or `verify_mcp_tools` |
| "GitLab?" | `verify_gitlab` — note MR tools exist, chat wiring is next |

---

## Mindset

You are not demoing a shipped product. You are demoing:

1. A **real business problem** (blocked colleagues when someone is absent)
2. A **working prototype** of the solution (twin + tools + bus)
3. A **credible path to production** (Copilot + Teams + Workday)

Mid-eval feedback was "WHERE IS THE AGENT?" — Part 1 answers that directly.

Rehearse out loud twice. First 60 seconds matter most.
