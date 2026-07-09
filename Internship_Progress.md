# Agent Social Network — Internship Progress Log

**Intern:** Shobhit Raj · IIT Patna · Engineering Intern  
**Project:** Agent Social Network (Team Productivity pillar)  
**Mentors:** Mayank Kumar, Prabhpreet Singh · **Buddy:** Harshad Yugraj  
**Repo / workspace:** `Agent Network Project` (Python, MCP, LangGraph)

---

## Project goal (reference)

Build an internal network where each employee has a **digital twin** agent with skills mapped to workplace tools (Jira, GitLab, Teams, Workday). Twins communicate with each other for task assignment and follow-up, reducing manual context-switching for routine coordination.

---

## Week 1 — Project setup & mock MVP (Days 1–4)

**Focus:** Understand scope, scaffold architecture, run first demo without real APIs.

**Completed:**
- Read project spec and defined a **4-week mock-first MVP** plan.
- Created Python package structure: `models`, `registry`, `bus`, `twin`, `mcp`, `demo`, `tests`.
- Implemented **digital twin agents** with skill-based access (Jira, GitLab, Teams, Workday).
- Built **agent-to-agent message bus** (assign, ack, status request/update).
- Implemented **mock MCP tool layer** (in-memory Jira/GitLab/Teams/Workday).
- Built first end-to-end demo: **`assign_and_track`** — reporter twin creates ticket, delegates to assignee twin, tracks completion.
- Added `.env.example`, README, pytest smoke tests.
- Prepared **mentor access checklist** (Jira sandbox, GitLab, Teams, Workday, MCP architecture).

**Outcome:** Runnable offline demo proving twin + bus + tool concept.

---

## Week 1–2 — Stabilization & mentor coordination (Days 5–8)

**Focus:** Fix demo reliability, Python compatibility, prepare for live integrations.

**Completed:**
- Fixed shared mock toolset bug (all twins now see same Jira store).
- Improved follow-up / status-check logic in `twin.py`.
- Python 3.9 compatibility fixes (`Optional` types, etc.).
- Documented **integration order**: Jira first → GitLab → Teams → Workday.
- Drafted emails/questions for mentors on MCP approach and sandbox access.

**Blockers / waiting on:** Jira project key, API token approval, GitLab/Teams/Workday access.

---

## Week 2 — Live Jira integration (Days 9–12)

**Focus:** Connect real Sprinklr Jira (LST sandbox) with safety guardrails.

**Completed:**
- Built **`live_jira.py`** — create, get, list, assign, close via REST API.
- Added **`config.py`** + `.env` driven mock/live mode switch.
- Utility scripts: `discover_jira_projects`, `discover_jira_issue_types`, `discover_jira_transitions`, `verify_jira`, `diagnose_jira`.
- **Demo safe mode:** tickets assign to intern only; `[Agent-Network-TEST]` prefix on new issues.
- **Legacy project protection:** assign/close blocked on tickets without safe prefix.
- Configured LST multi-step close workflow (`IN PROGRESS → IN REVIEW → CLOSED`).
- Successfully created and closed live test tickets (e.g. LST-46547, LST-45492).
- Resolved Jira API token expiry issue (regenerated token).

**Outcome:** Live Jira read/write working in controlled sandbox.

---

## Week 2–3 — Manager view & read-only workflows (Days 13–16)

**Focus:** Safe live demos for “review progress” without modifying production issues.

**Completed:**
- Built **`review_tasks`** demo — read-only Jira ticket summary for managers.
- Extended live Jira with **`list_tickets`** (JQL, demo-prefix filter).
- Added **`TaskReviewReport`** model and manager-facing summary text.
- Built **GitLab read-only** client (`live_gitlab.py`): list MRs, link MR → Jira comment.
- Scripts: `verify_gitlab`, `discover_gitlab_projects`.
- Teams & Workday remain **mock** (pending mentor/API access).

**Outcome:** Two demo modes — write flow (`assign_and_track`) and read flow (`review_tasks`).

---

## Week 3 — LangGraph & MCP server (Days 17–20)

**Focus:** Orchestration layer + expose tools to Cursor / external agents.

**Completed:**
- Implemented **LangGraph assign-and-track flow** (`delegate → complete → track → END`).
- Demo: `assign_and_track_graph.py`.
- Built **MCP stdio server** (FastMCP) with 10 tools: Jira CRUD, GitLab list/link, Teams notify, Workday manager lookup, status.
- Resolved MCP/Cursor integration issues (path spaces, venv, global `mcp.json`, symlink).
- Smoke test: `verify_mcp_tools.py`; all pytest tests passing.
- Renamed sample twins to **Demo Manager / Assignee / Observer** (no real employee names in demos).

**Outcome:** MCP server green in Cursor; LangGraph workflow demo-ready.

---

## Week 3 — Mid-internship evaluation (Days 21–24)

**Focus:** Presentation, demo script, progress summary for mentors.

**Completed:**
- Prepared **15-min mid-eval talk track** (problem, users, demo, vision, blockers).
- Built presentation deck: `presentation/Mid_Intern_Evaluation_Agent_Network.pptx`.
- Demo plan: LangGraph live + MCP in Cursor + `review_tasks`.
- Estimated progress: ~65–70% of written spec deliverables; ~45–50% of full production vision.

**Feedback received:**
- Jira create/list/assign alone doesn’t feel novel — expected **human-to-agent** interaction.
- Core product vision: when an employee is **absent**, colleagues should **message their digital twin** and get unblocked (Copilot/Teams channel, twin acts with user’s permissions).
- MCP tools are fine; need **conversational agent layer** on top (LLM / MS Copilot).

---

## Week 4 — Human-to-twin chat (Days 25–28)

**Focus:** Address mentor feedback — “WHERE IS THE AGENT?”

**Completed:**
- Added **`is_absent`** flag on employees (Demo Manager = absent / stand-in mode).
- New MCP tool: **`twin_delegate_ticket`** (create + agent bus delegation via shared **`runtime.py`**).
- Built **`TwinChatSession`** — rule-based chat router (list / get / delegate); LLM-ready architecture.
- Added **`access_policy.py`** — stand-in judgment (colleagues see their blockers, not the twin owner’s full private queue).
- **Requester identity:** `--as` in CLI, “You are” selector in Streamlit; list/get scoped to requester vs twin owner.
- CLI demo: **`talk_to_twin.py`**.
- **Streamlit browser UI:** `twin_chat_app.py`.
- Mock mode seed tickets (so list/status flows work offline).
- Fixed ticket ID regex for mock keys (`JIRA-XXXX` not only `LST-12345`).
- Twin action **audit log** (`.twin-audit.jsonl`).
- Restored full codebase after accidental Cursor “Undo All” data loss; tests passing.

**Outcome:** End-to-end human-to-twin flow with real MCP tool calls (list, get, delegate) and access scoping.

---

## Week 5 — Copilot Studio channel & MCP stability (Days 29–32)

**Focus:** Production conversation channel (Copilot/Teams path) + restore Cursor MCP integration.

**Completed:**
- Created **Copilot Studio test agent** (`Agent Network Demo - TEST`) in Sprinklr tenant (private, unpublished).
- Built **stand-in Topics** for absent-manager scenario: About this agent, Absent colleague help; updated **Greeting** for stand-in narrative.
- Confirmed **Copilot license limitation:** generative **Instructions** and **Actions** unavailable on current plan (requires Copilot Studio User License / trial upgrade for LLM orchestration and tool wiring).
- Documented **production architecture split:** Copilot = LLM + Teams channel; Python MCP `tools_registry` = tool execution; Streamlit = dev UI until Copilot Actions connect.
- Restored **Cursor MCP config** (`~/.cursor/mcp.json`) after accidental deletion; verified **11 tools** via `verify_mcp_tools`.
- Resolved duplicate MCP server entries (global config only; symlink path `/Users/shobhit.raj/agent-network-project` + `.venv-mcp` FastMCP server).

**In progress / next:**
- Copilot **generative Instructions + Actions** → Python MCP (blocked on license).
- **Workday** roster loader or API (one twin per employee from HR data).
- **Teams** live Graph API (mock notify works; owner alerts on delegate ✅).
- Per-user Jira auth model for true stand-in behavior.

---

## Week 6 — Owner coordination, GitLab, LLM scaffold (current)

**Focus:** Complete product flows before presentation week.

**Completed:**
- **`TwinStandInPolicy`** — delegate rules, Teams notify on delegate, default assignee; persisted in `.twin-standin-policies.json`.
- **Owner ↔ own twin** — `go absent` / `go present`, `stand-in settings`, `stand-in rules`, `what happened while I was away?` (audit digest).
- **Proactive owner notify** — on delegate while absent, twin sends Teams message (mock; bypasses demo safe mode via `owner_stand_in` purpose).
- **GitLab in twin chat** — `list merge requests`, `link MR <url> to TICKET-ID`; mock MR seed data.
- **LLM router** (`agent/llm_router.py`) — OpenAI tool-calling over MCP tools when `OPENAI_API_KEY` set; keyword fallback otherwise.
- **Streamlit** — owner stand-in controls (absent toggle, policy checkboxes, activity feed, mock Teams notification count).
- **14 tests passing** (owner absence, GitLab list, delegate + notify).

**Outcome:** Two-sided twin product — owner configures stand-in; colleagues get help; owner notified and can review activity.

**LLM strategy (dual path — compare when Copilot license lands):**

| Path | Role | Status |
|------|------|--------|
| **Ollama (local)** | Gen AI + tool-calling in Python twin chat | ✅ Wired — `OLLAMA_ENABLED=true` |
| **Copilot Studio** | Production Teams channel + generative Instructions | 🟡 Topics only; license pending |
| **Shared backend** | Both call same `tools_registry` / MCP tools | ✅ |

When Copilot generative access is granted: add Actions → same MCP HTTP or Jira connector; keep Ollama for dev/demo. Pick best UX for eval after both work.

---

## Week 7 — Deployable Teams product: LLM, memory, presence, real A2A (current)

**Focus:** Address second-round mentor feedback — must be a deployable, AI-driven Teams product, not a prototype.

**Completed:**
- **Real LLM brain** (`agent/llm_router.py`): provider abstraction over **Grok (x.ai)**, **Ollama (local)**, or OpenAI via one OpenAI-compatible client + tool-calling against MCP tools; keyword router demoted to fallback. `verify_ollama` smoke test.
- **Per-conversation memory** (`memory.py`): SQLite store; recent turns injected into the LLM so each agent processes follow-ups with context. Keyed by conversation id (Teams conversation / session).
- **Presence-based absence** (`absence.py`): twin is "effectively absent" via manual flag **or** owner-scheduled windows **or** Microsoft Teams presence (Graph). 
- **Owner commands twin behaviour** (`twin_chat.py` + `standin_policy.py`): `instructions: …` (free-text directions injected into LLM prompt) and `absent from <date> to <date>` (scheduled windows). Persisted to `.twin-standin-policies.json`.
- **Real agent-to-agent over HTTP** (`a2a/`): stdlib HTTP server + client + `HttpAgentBus`; twins run as separate services and deliver `AgentMessage`s across the network (`A2A_PEERS`). Demos: `a2a_server`, `a2a_send`.
- **Microsoft Teams bot** (`teams/bot.py`, `teams/app.py`): Bot Framework handler routes Teams chat → correct twin (`talk to <name>`), resolves requester identity, replies in Teams; `/api/a2a` and `/healthz` on the same service. `teams/graph_presence.py` reads presence via Graph (client-credentials, `Presence.Read.All`).
- **Deploy artifacts**: `Dockerfile`, `requirements-teams.txt`, `teams_app/manifest.json`, `DEPLOYMENT.md` (Azure Container Apps / App Service + tunnel testing + bring-me list).
- Heavy deps (botbuilder/msal/aiohttp) imported lazily — core stays importable and **21 tests pass**.

**Blocked on Sprinklr IT (for live Teams deploy):** Entra app registration, Azure Bot resource, Graph admin consent, custom-app upload, public HTTPS host. Code is complete and waits on credentials.

---

## Deliverables checklist (from project spec)

| Deliverable | Status |
|-------------|--------|
| Digital twin per employee + skills | ✅ Done (demo registry) |
| MCP integrations — Jira | ✅ Live (sandbox) |
| MCP integrations — GitLab | 🟡 Read-only live |
| MCP integrations — Teams | 🟡 Mock only |
| MCP integrations — Workday | 🟡 Mock only |
| Agent-to-agent protocol | ✅ Done (bus + message types) |
| Task assignment + follow-up automation | ✅ Done |
| Demo: assign ticket + track completion | ✅ Done (script + LangGraph) |
| Human-to-twin chat (mentor priority) | ✅ Done (CLI + Streamlit + access policy) |
| Copilot / Teams deployment | 🟡 Copilot agent + Topics; generative/tools blocked on license |
| GitLab in twin chat flow | ✅ Done |
| Owner ↔ own twin + stand-in policy | ✅ Done |
| Owner notify on delegate (Teams mock) | ✅ Done |
| LLM brain (Grok / Ollama, tool-calling) | ✅ Done (set provider in `.env`) |
| Per-conversation memory (context) | ✅ Done (SQLite) |
| Owner instructions + absence windows | ✅ Done |
| Presence-based absence (Teams/Graph) | ✅ Code done; needs Graph creds |
| Real agent-to-agent over HTTP | ✅ Done (`a2a/`) |
| Teams bot + deploy artifacts | ✅ Code done; needs Azure/Teams creds |

---

## How to run current demos

```bash
cd "Agent Network Project"
source .venv/bin/activate

# Agent-to-agent (terminal)
PYTHONPATH=. python -m agent_network.demo.assign_and_track_graph

# Human-to-twin chat (terminal)
AGENT_NETWORK_MODE=mock PYTHONPATH=. python -m agent_network.demo.talk_to_twin

# Human-to-twin chat (browser)
AGENT_NETWORK_MODE=mock PYTHONPATH=. streamlit run agent_network/demo/twin_chat_app.py

# Read-only manager view
PYTHONPATH=. python -m agent_network.demo.review_tasks

# Tests
PYTHONPATH=. pytest tests/ -q
```

---

## Blockers & asks for mentors

1. **Copilot Studio license:** Assign **Copilot Studio User License** (or confirm trial OK) so generative Instructions + Actions are available; current plan is Topics-only.
2. **Copilot → MCP wiring:** Should we use Copilot’s Jira connector or expose Python `tools_registry` via HTTP API for twin delegate / bus flows?
3. **Teams publish:** OK to publish test agent to a private Teams channel, or Test panel only?
4. **Workday / roster:** API access or approved employee CSV for one-twin-per-employee and automatic absence.
5. **GitLab:** Confirm sandbox project for MR linking in twin workflows.
6. **Twin auth model:** How should an absent employee’s twin authenticate as them in Jira?

---

## Architecture (current)

```
Human (Streamlit / future Teams)
    → TwinChatSession or Copilot Topics (conversation)
    → tools_registry.call_tool()  OR  DigitalTwinAgent + get_toolset()
    → MCP tool layer (Jira / GitLab / Teams mock / Workday mock)
    → Agent bus (twin-to-twin delegate / track)

Cursor IDE → MCP protocol (stdio FastMCP) → same tools_registry
```

---

*Last updated: Week 5 of internship (post Copilot Studio setup + MCP restore)*
