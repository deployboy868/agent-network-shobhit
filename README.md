# Agent Social Network (Internship MVP)

Internal network where each **node** is a **digital twin** of an employee: an AI agent that can use workplace tools (Jira, GitLab, Teams, Workday) and talk to other agents to assign work and follow up—without a human copying context between systems.

This repo starts **mock-based** so you can build and demo without real API access. Real MCP integrations plug in later via `.env` credentials.

## Integration timeline (when to add each system)

| When | System | Start when… |
|------|--------|-------------|
| **Now (Week 2)** | Jira list/review | ✅ Built — read-only `review_tasks` |
| **Week 2 end** | Teams | Mentor confirms Copilot test channel OR Graph API access |
| **Week 3 start** | GitLab | Mentor gives test project + token |
| **Week 3 mid** | Workday | Mentor gives sandbox API or approved employee CSV |
| **Week 3 end** | MCP server + LangGraph | LangGraph assign flow ✅ — MCP server next |

Do **not** start GitLab/Teams/Workday until Jira **review_tasks** works and mentor replies on access.

### GitLab without UI access

If GitLab web login is blocked but you have a token + base URL:

```bash
PYTHONPATH=. python -m agent_network.demo.discover_gitlab_projects
```

If that fails, ask mentor for **GITLAB_PROJECT_ID** or **path** of a sandbox project.

```bash
PYTHONPATH=. python -m agent_network.demo.verify_gitlab
```

Lists open MRs read-only. Linking MR → Jira adds a **Jira comment only** (GitLab unchanged).

## Quick start

```bash
cd "/Users/shobhit.raj/Downloads/Agent Network Project"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m agent_network.demo.assign_and_track
```

### LangGraph orchestration (same demo, explicit graph)

```bash
PYTHONPATH=. python -m agent_network.demo.assign_and_track_graph
```

Runs **delegate → complete → track** as a LangGraph state machine. Works in mock or live mode (same `.env` as `assign_and_track`).

### MCP server (expose tools to Cursor / agents)

```bash
PYTHONPATH=. python -m agent_network.demo.verify_mcp_tools
```

Smoke-test tools in-process. To run the stdio server (for Cursor MCP):

```bash
PYTHONPATH=. python -m agent_network.mcp_server
```

Add to Cursor **Settings → MCP** using `mcp.cursor.json.example` (update paths). Tools: Jira create/list/assign/close, GitLab list MRs, link MR→Jira comment — same safety rules as demos.

## Find your Jira project key (no mentor needed if API works)

If you have URL + email + token but not the project key yet:

```bash
PYTHONPATH=. python -m agent_network.demo.discover_jira_projects
```

Pick a sandbox project from the list and set `JIRA_PROJECT_KEY` in `.env`.

## Connect real Jira (after you get an API token)

1. Copy `.env.example` to `.env` (if you have not already).
2. Fill in these values:

   | Variable | What to put |
   |----------|-------------|
   | `AGENT_NETWORK_MODE` | `live` |
   | `JIRA_BASE_URL` | Your site, e.g. `https://sprinklr.atlassian.net` (no trailing slash) |
   | `JIRA_EMAIL` | Your Atlassian login email |
   | `JIRA_API_TOKEN` | The token you created |
   | `JIRA_PROJECT_KEY` | Sandbox project key from mentor |
   | `JIRA_ISSUE_TYPE` | Usually `Task` (must exist in that project) |

3. Test the connection (creates one real test ticket):

```bash
source .venv/bin/activate
PYTHONPATH=. python -m agent_network.demo.verify_jira
```

4. Run the full agent demo (creates another ticket, assigns, marks done):

```bash
PYTHONPATH=. python -m agent_network.demo.assign_and_track
```

### Review tasks (read-only, safe for live Jira)

```bash
PYTHONPATH=. python -m agent_network.demo.review_tasks
```

Lists only `[Agent-Network-TEST]` tickets in live mode — does not create or change anything.

**Important:** Assignee emails in `agent_network/registry.py` must match real Jira users in that project, or assignment will fail.

### Safety on legacy / inactive projects

If the project has **old tickets you must not touch**:

1. Set `JIRA_SAFE_PREFIX=[Agent-Network-TEST]` in `.env` (default).
2. The app **only creates new** issues with that prefix in the title.
3. **Assign** and **mark done** are **blocked** for any issue without that prefix.
4. After demos, delete only tickets you created (search by the prefix in Jira).

**Safe order:** `verify_jira` first (one test ticket) → then `assign_and_track`.

### Don't ping colleagues during demos

Set `JIRA_DEMO_SAFE_MODE=true` (default). Live demos will:
- Assign Jira tickets to **you** (`JIRA_EMAIL`) only — not managers/colleagues
- **Not** send Teams notifications
- Still run the **agent-to-agent** message flow in code for the demo story

Only set `JIRA_DEMO_SAFE_MODE=false` if your mentor explicitly wants real assignments.

### LST multi-step workflow (close tickets)

If your project cannot close in one step (e.g. Need Review → In Progress → In Review → Closed), add to `.env`:

```env
JIRA_CLOSE_WORKFLOW=enabled
```

LST workflow (from your Jira UI):

**From IN PROGRESS:** options are IN PROGRESS | NEED REVIEW | **IN REVIEW** → pick **IN REVIEW** (skip NEED REVIEW)

**From IN REVIEW:** options are TO DO | **CLOSED** | IN PROGRESS → pick **CLOSED**

```
… → IN PROGRESS → IN REVIEW → CLOSED
```

`.env`:
```env
JIRA_CLOSE_WORKFLOW=enabled
JIRA_DONE_TRANSITION=CLOSED
```

If verify fails with **"Specify a valid issue type"**, list valid types for your project:

```bash
PYTHONPATH=. python -m agent_network.demo.discover_jira_issue_types
```

Copy an exact name into `JIRA_ISSUE_TYPE` in `.env`, save, and retry `verify_jira`.

## Project layout

```
agent_network/          # Python package
  models.py             # Employee, task, message types
  registry.py           # Who works here (digital twins)
  bus.py                # Agent-to-agent message bus
  twin.py               # Digital twin agent logic
  graph/                # LangGraph workflows (assign-and-track)
  mcp/                  # Tool layer (mock now, real later)
  mcp_server/           # MCP stdio server (Cursor / agents)
  demo/                 # End-to-end demo script
tests/                  # Small tests
.env.example            # Where secrets go (copy to .env)
requirements.txt
```

## Docs

- Project spec: `Project_Description.txt`
- Mentor access checklist: see README section "Access to request" in this file (also in chat summary)
