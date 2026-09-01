# Demo Day walkthrough (5–10 min)

Live UI: https://ai-internship-streamlit-ui.onrender.com — open this before you start talking, cold starts on Render's free tier can take ~20–30s.

## 0:00–0:30 — The problem, in one breath

"When something breaks in production, the on-call engineer's first move is 'has this happened before, and what fixed it?' — but that answer is scattered across old runbooks and postmortems. This agent answers on-call questions for a Shopify Plus-style ecommerce platform, grounded in the team's real docs — cites what it used, and won't make up a source it doesn't have." (Knowledge base models real Shopify Plus mechanics — Admin API, custom-domain SSL, inventory sync — worth naming if the room is technical.)

## 0:30–2:00 — Core task, live

**Agent tab.** Ask a real question, e.g. *"Redis cache is showing a spike in errors, what should I check first?"* Point out in the answer: it names the actual runbook/postmortem IDs it used (`runbook_redis_cache_stampede`, not a generic "I found this in the docs"). That's the grounding, not a canned response.

## 2:00–4:00 — The eval story (this is what separates it from a bare demo)

"I didn't just ship this and hope — I ran a TRACE process on it." In one breath:
1. Open-coded 20 sample traces + 15+ of my own runs, free-text notes first, no metrics.
2. Built a failure taxonomy, ranked by frequency × impact.
3. Top failure: the agent sometimes said "sources needed" but attached citations inconsistently — a real grounding gap.
4. Two prompt-only fixes helped but didn't close it. Shipped a **code-level** fix instead: force-clear citations whenever the consistency check fails, don't trust the model to self-police.

**Eval tab**, live questions mode, toggle `DEMO_DISABLE_CITATION_GUARD` on Render env if you want to show it moving live: guard off → 54–69% consistency; guard on (shipped) → **13/13, 100%**. If no time to toggle live, show the frozen-dataset screenshot instead — same 13/13 result, deterministic, no live-call variance.

## 4:00–5:30 — Two transports, one core (the MCP stretch goal)

"The same retrieval logic is reachable two ways: a direct function-tool call (`/agent`), and an MCP server (`/agent/mcp`) — same answers, different protocol, both traced." Worth one sentence on the real bug this surfaced: MCP's stdio subprocess doesn't inherit the parent's environment by default, so this passed locally (there was a `.env` file on disk) and broke in production (secrets come from real env vars) — root-caused from Render logs, fixed with one line (`env=os.environ.copy()`).

## 5:30–7:30 — Durable memory, cross-session

**Memory tab.** Write something through the gate: *"Always page the DBA on-call for database issues, not general platform on-call."* Show the gate's decision (persisted, with the distilled key/value). Then try a one-off question — *"What's the current error rate on checkout?"* — show it gets discarded, not written. That's the point: not everything is worth remembering.

Then prove it's not just in-browser state: open a terminal, run `python memory_cli.py read <key>` — a completely separate process hitting the same deployed API — and show the fact comes back. Mention it survives a full server restart, not just a page reload, because it's backed by Pinecone, not local disk (which Render wipes on every restart/redeploy).

## 7:30–9:00 — Observability

One Langfuse trace, opened live if the dashboard's handy: point out the `environment` tag, the `transport:function-tool` vs `transport:mcp` tag, and that this exists specifically because an earlier version of this tracing silently took down the whole app on bad credentials — fixed by making tracing failures non-fatal.

## 9:00–10:00 — Close

"FastAPI + Google ADK agent, grounded on Pinecone, two transports, Langfuse-traced, with a durable memory store separate from the RAG knowledge base — and every claim I just made has a number or a log behind it, not just a demo that happened to work once." Point to the repo and the [one-page brief](BRIEF.md) for anyone who wants the detail after.
