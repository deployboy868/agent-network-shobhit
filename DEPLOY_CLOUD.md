# Deploy a permanent demo link (no laptop required)

The Cloudflare tunnel (`trycloudflare.com`) only works while **your Mac is on**. For user evaluation, deploy to the cloud once and submit a **permanent URL**.

---

## Option A — Streamlit Community Cloud (recommended, free)

**URL looks like:** `https://your-app-name.streamlit.app`  
**Stays up:** Yes (free tier; no laptop needed)

### Steps (~20 minutes)

1. **Push this project to GitHub** (private repo is fine)
   ```bash
   cd "/Users/shobhit.raj/Downloads/Agent Network Project"
   git init
   git add .
   git commit -m "Agent Social Network demo"
   # Create repo on github.com, then:
   git remote add origin https://github.com/YOUR_USER/agent-network.git
   git push -u origin main
   ```

2. **Go to** https://share.streamlit.io → Sign in with GitHub

3. **New app**
   - Repository: your repo
   - Branch: `main`
   - Main file path: **`streamlit_app.py`**
   - App URL: pick something like `agent-network-shobhit`

4. **Advanced settings → Secrets** (paste as TOML):
   ```toml
   GROQ_API_KEY = "your-groq-key"
   LLM_PROVIDER = "groq"
   AGENT_NETWORK_MODE = "mock"
   TWIN_MEMORY_DB = ".twin-memory.db"
   ```
   For **live Jira** in cloud, also add `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`, etc.

5. **Deploy** → copy the `.streamlit.app` link → **submit that for evaluation**

---

## Option B — Render.com (Docker, free tier)

**URL looks like:** `https://agent-network-demo.onrender.com`  
**Caveat:** Free tier **sleeps after ~15 min idle**; first visit takes ~30–60s to wake.

1. Push to GitHub (same as above)
2. https://render.com → New → **Blueprint** → connect repo
3. It reads `render.yaml` automatically
4. Add **GROQ_API_KEY** in Render dashboard when prompted
5. Deploy → submit the `onrender.com` link

---

## Option C — Keep using tunnel (temporary only)

Only if you need a link **in the next 5 minutes** and can keep the Mac on for a few hours:

```bash
./scripts/docker-run.sh
./scripts/share-demo.sh
```

Copy the `https://….trycloudflare.com` URL. **Stops when you close the laptop.**

---

## What to submit for user evaluation

```
Live demo: https://YOUR-APP.streamlit.app

Instructions:
1. Open link in Chrome
2. Sidebar: You are = Demo Intern, Talking to twin of = Demo Manager (absent)
3. Ask: "I've been assigned to create a sprint planner — can you assign me a ticket?"
4. Second tab (incognito): You are = Demo Manager, approve TA-1

See USER_EVALUATION.md in repo for full script.
```

---

## Mock vs live in cloud

| Mode | Pros | Cons |
|------|------|------|
| **mock** | No VPN, no Jira secrets, always works | Tickets are fake |
| **live** | Real LST tickets | Needs Jira creds in secrets; Sprinklr VPN may block Render servers |

For evaluation submission, **mock + Groq** is the most reliable.
