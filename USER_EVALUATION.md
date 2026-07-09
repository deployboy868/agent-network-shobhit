# Agent Social Network — User Evaluation Link

## Live demo URL

**https://lake-preparing-mph-cute.trycloudflare.com**

Open in any browser (Chrome recommended). No install required.

> **Note for evaluator:** This link only works while the intern’s laptop is on and the demo stack is running. If the page does not load, contact Shobhit Raj.

---

## What to test (5–10 minutes)

### Setup in the sidebar

| Setting | Value |
|---------|--------|
| **You are** | Demo Intern |
| **Talking to twin of** | Demo Manager **(absent)** |

### Scenario A — Colleague blocked on work

1. Say: *"I've been assigned the task to create a sprint planner by my manager, can you assign me a ticket for the same?"*
2. Twin should queue the request and notify the manager (not create the ticket immediately).

### Scenario B — Manager approves (second browser or incognito tab)

1. **You are:** Demo Manager · **Talking to:** own twin  
2. Say: *"notify and confirm with me before creating tickets"* (if not already set)  
3. Say: *"go absent"*  
4. Check chat for proactive alert **TA-1** (or latest TA-X)  
5. Say: *"approve TA-1"*  
6. Intern tab should show ticket created.

### Scenario C — Owner standing rules

1. **Manager tab:** *"tell people wanting Copilot Studio generative AI access to request on myaccess"*  
2. **Intern tab:** *"Where do I get generative AI access on Copilot Studio?"*  
3. Twin should answer with **myaccess** guidance (not a generic greeting loop).

### Optional

- `list my tickets` — scoped to your work  
- `list merge requests` — GitLab integration  
- Manager: *"what happened while I was away?"* — audit recap  

---

## Product summary (for reviewers)

**Agent Social Network** — digital twins that stand in when an employee is absent. Colleagues chat with the twin; it uses Jira/GitLab/Teams, follows owner rules, queues ticket approvals, and logs actions for audit.

---

## Technical stack

- Streamlit UI + Groq LLM + live Jira (sandbox) + Docker  
- Public link via Cloudflare Tunnel → `localhost:8501`

---

**Intern:** Shobhit Raj · IIT Patna · Sprinklr Engineering Intern
