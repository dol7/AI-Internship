# One-page brief — on-call incident triage agent

**Live:** UI [ai-internship-streamlit-ui.onrender.com](https://ai-internship-streamlit-ui.onrender.com) · API [ai-internship-5euv.onrender.com](https://ai-internship-5euv.onrender.com) · [source](https://github.com/dol7/AI-Internship)

## Problem

When something breaks in production, the on-call engineer's first move is usually "has this happened before, and what fixed it?" — but that answer is scattered across old runbooks, postmortems, and whoever remembers the last incident. This agent answers on-call questions grounded in the team's actual runbooks and postmortems, cites what it used, refuses to fabricate a source when it doesn't have one, and remembers standing rules across sessions instead of re-asking every time.

## Architecture

Streamlit UI (thin client) → FastAPI (`main.py`) → Google ADK `Agent`/`Runner` → `search_runbooks()` tool → Pinecone (RAG documents). A second transport (`/agent/mcp`) reaches the same retrieval core through an MCP server instead of a direct function-tool call. A separate durable-memory path (`/memory*`) writes to its own Pinecone namespace, gated by a small classifier so only stable facts persist. Both transports are traced through Langfuse. Full diagram: [README.md § Capstone](README.md#capstone-on-call-incident-triage-agent).

## Stack

FastAPI · Google ADK · OpenAI (`gpt-4o` answers, `gpt-4o-mini` memory gate, structured outputs via `chat.completions.parse`) · Pinecone · MCP (`FastMCP`) · Langfuse · Streamlit · Render.

## What TRACE proved, and the fix shipped

Open-coded 20 sample traces + 15+ of my own capstone runs into a 4+ category failure taxonomy, ranked by frequency × impact. Top failure: the agent sometimes asserted `sources_needed=true` but attached citations inconsistently — a real grounding gap. Two rounds of prompt-only fixes each helped but didn't close it. Shipped a deterministic code-level fix (`rag_core.py` force-clears citations when the consistency check fails, instead of trusting the model). Result on the same 13 real questions: **54–69% → 100%** (`sources_needed_citation_consistency`), confirmed on every run since.

## Durable memory — the five answers

- **What** it stores: stable corrections, preferences, and last-successful-fix notes — never ephemeral tool output.
- **When** it writes: directly (`PUT /memory/{key}`) or gated (`POST /memory/write-gated`, a `gpt-4o-mini` classifier that discards one-off questions and raw tool output).
- **Where** it lives: a dedicated `"memory"` Pinecone namespace — not local disk, which Render's free tier wipes on every restart/redeploy.
- **How** it's retrieved: plain key/value fetch (`GET /memory/{key}` or `GET /memory`), no similarity search.
- **When it's forgotten:** only on explicit `DELETE /memory/{key}` — no TTL/auto-expiry yet, so "forget" is a human decision today, not automatic.

Full detail: [README.md § Durable memory](README.md#durable-memory).
