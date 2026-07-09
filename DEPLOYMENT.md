# Deployment Guide — Agent Social Network on Microsoft Teams

This deploys the digital-twin agents as a **Teams bot** backed by an LLM, with
per-conversation memory, real agent-to-agent messaging, presence-based absence,
and owner stand-in instructions.

```
Teams user ── 1:1/channel chat ──► Bot (/api/messages)
                                     │
                          TwinChatSession (per conversation_id)
                                     │
                     LLM (Grok / Ollama) ──► MCP tools (Jira, GitLab, delegate)
                                     │                       │
                       conversation memory (SQLite)     Agent bus / A2A (/api/a2a)
                                     │
                     presence (Graph) + owner absence windows + instructions
```

---

## 0. What you must obtain (the "bring me" list)

| # | Item | Where | Used for |
|---|------|-------|----------|
| 1 | **Entra app registration** → `TENANT_ID`, client id, client secret | Azure Portal → Entra ID → App registrations | Bot auth + Graph |
| 2 | **Azure Bot resource** → `MICROSOFT_APP_ID`, `MICROSOFT_APP_PASSWORD` | Azure Portal → Azure Bot | Teams messaging |
| 3 | Graph permission **`Presence.Read.All`** (application) + **admin consent** | Entra app → API permissions | Read Teams status |
| 4 | **Teams admin**: allow custom app upload (sideload) | Teams Admin Center | Install the app |
| 5 | **Public HTTPS host** | Azure App Service / Container Apps | Bot endpoint must be https |
| 6 | **LLM**: `GROK_API_KEY` (cloud) and/or local **Ollama** | x.ai / ollama.com | Reasoning |

Items 1–5 require Sprinklr IT/admin. Start that request now; build/test locally meanwhile.

---

## 1. Local run (no Teams, full brain) — works today

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Optional local LLM:
#   ollama pull llama3.1 && export OLLAMA_ENABLED=true
AGENT_NETWORK_MODE=mock PYTHONPATH=. streamlit run agent_network/demo/twin_chat_app.py
```

Verify LLM wiring:
```bash
PYTHONPATH=. python -m agent_network.demo.verify_ollama   # if using Ollama
```

## 2. Real agent-to-agent over HTTP (two services)

```bash
# Terminal 1: assignee twin service
PYTHONPATH=. python -m agent_network.demo.a2a_server --port 8766
# Terminal 2: manager delegates to assignee across the network
A2A_PEERS='{"twin-emp-assignee":"http://localhost:8766"}' \
  PYTHONPATH=. python -m agent_network.demo.a2a_send --url http://localhost:8766
```

When `A2A_PEERS` is set, the runtime bus delivers messages to peer twins over HTTP.

---

## 3. Teams bot — local test with a tunnel

```bash
pip install -r requirements-teams.txt
# .env: MICROSOFT_APP_ID, MICROSOFT_APP_PASSWORD, GROK_API_KEY (or OLLAMA), TEAMS_USER_MAP
PYTHONPATH=. python -m agent_network.teams.app    # serves :3978
```

Expose it (pick one):
```bash
devtunnel host -p 3978 --allow-anonymous     # Microsoft dev tunnels
# or: ngrok http 3978
```

In the **Azure Bot** resource, set **Messaging endpoint** to:
`https://<your-tunnel>/api/messages`

Package the Teams app:
1. Edit `teams_app/manifest.json` — replace `${MICROSOFT_APP_ID}` and `${BOT_DOMAIN}` (your tunnel/host domain).
2. Add `color.png` (192×192) and `outline.png` (32×32) to `teams_app/`.
3. Zip the three files → `manifest.zip`.
4. Teams → Apps → **Manage your apps → Upload a custom app** → pick the zip.

Chat the bot: `talk to demo manager`, `list my tickets`, `go absent`, `instructions: only delegate P0 to assignee`.

---

## 4. Build & run the Docker image (local)

**Prerequisite:** [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) installed and running.

```bash
# Build
./scripts/docker-build.sh
# or: docker build -t agent-network:latest .

# Run (reads .env, persists memory in a Docker volume)
./scripts/docker-run.sh
# or: docker compose up --build
```

Smoke test:
```bash
curl http://localhost:3978/healthz
# {"status": "ok"}
```

The image runs the **Teams + A2A** service only (`agent_network.teams.app` on port 3978).
It uses `requirements-docker.txt` (lean — no Streamlit/LangGraph). For the Streamlit dev UI,
keep using `pip install -r requirements.txt` on the host.

---

## 5. Deploy to Azure (production host)

Containerized (recommended):
```bash
# Build & push
az acr create -n <registry> -g <rg> --sku Basic
az acr build -r <registry> -t agent-network:latest .

# Azure Container Apps (or App Service for Containers)
az containerapp create \
  -n agent-network -g <rg> \
  --image <registry>.azurecr.io/agent-network:latest \
  --target-port 3978 --ingress external \
  --env-vars MICROSOFT_APP_ID=... MICROSOFT_APP_PASSWORD=... \
             TENANT_ID=... GRAPH_CLIENT_ID=... GRAPH_CLIENT_SECRET=... \
             GROK_API_KEY=... LLM_PROVIDER=grok \
             AGENT_NETWORK_MODE=live JIRA_BASE_URL=... JIRA_EMAIL=... JIRA_API_TOKEN=... \
             JIRA_PROJECT_KEY=... TEAMS_USER_MAP='{"you@company.com":"emp-manager"}'
```

Set the Azure Bot **Messaging endpoint** to `https://<container-app-fqdn>/api/messages`.
Health check: `GET https://<host>/healthz`.

Notes:
- Use **Grok** (cloud) for the deployed host — Ollama on localhost is not reachable from Azure.
- For real Jira, set `AGENT_NETWORK_MODE=live` and keep `JIRA_DEMO_SAFE_MODE=true` until sign-off.
- Mount a volume or use a managed DB for `TWIN_MEMORY_DB` if you want memory to persist across restarts.

---

## 6. Feature → mentor-requirement map

| Requirement | Where |
|-------------|-------|
| Deployable product | `Dockerfile`, this guide, `teams/app.py` |
| Real AI (Grok/Ollama) | `agent/llm_router.py`, `config.llm_provider` |
| Teams chat + presence | `teams/bot.py`, `teams/graph_presence.py`, `teams_app/manifest.json` |
| Per-chat context stored | `memory.py` (SQLite, fed to LLM) |
| Real agent-to-agent | `a2a/` (HTTP server + client + network bus) |
| Owner commands twin behavior | `instructions:` / `absent from … to …` / `stand-in rules` |
| Presence-based absence + manual windows | `absence.py` |
