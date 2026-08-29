# CLAUDE.md

Instructions for any coding agent (Claude Code or otherwise) working in this
repo. This file is meant to survive context compaction — if everything else
in a session's context gets summarized away, these rules should not.

## Critical rules (keep these above the compaction line)

1. **Never commit `.env` or any real secret.** Check `git status --ignored | grep -i "\.env"` shows it ignored after every push, not just before. Secrets live in Render's env var UI, not in files.
2. **Never claim a fix works without running it for real.** Local import success, syntax checks, and "this should work" are not verification. Hit the actual endpoint, run the actual eval, read the actual logs/screenshot before saying something is fixed or shipped.
3. **The durable memory store (`memory_store.py`) is gated on purpose.** Only `gate_and_write()` or an explicit `PUT /memory/{key}` may write to the `"memory"` Pinecone namespace. Never write raw tool output, retrieved chunk text, or one-off diagnostic answers there — that's what the gate in `memory_store.py`'s `GATE_PROMPT` exists to reject. If you're tempted to persist something "just in case," that's the signal it belongs in a trace/log, not memory.
4. **Render's free tier wipes local disk on every restart/redeploy, and free Postgres force-deletes after 30+14 days.** Both verified against Render's own docs. Do not reintroduce SQLite-on-local-disk or assume Postgres is safe to treat as permanent without re-checking that constraint.
5. **The citation-consistency guard in `rag_core.py` (`if parsed.sources_needed and parsed.citations: parsed.citations = []`) is a deterministic fix, not a suggestion.** Do not revert it to a prompt-only approach — two rounds of prompt-only fixes were tried and measured as incomplete/inconsistent (see eval history) before this code-level fix landed at 13/13.
6. **`DEMO_DISABLE_CITATION_GUARD` only affects live calls, not the frozen eval dataset (`eval_dataset/oncall-capstone-traces-annotated.jsonl`).** Don't use frozen-dataset mode to demonstrate the toggle's effect — it's architecturally immune to it.
7. **Before deleting or overwriting a file, read what's actually in it first**, especially anything under `PC/USA_CANADA/` or other non-code project directories this agent didn't author — don't assume based on a filename.
8. **Ask before pushing to git or deploying**, unless already mid-task with the user's active go-ahead. Confirm the diff first.

## Where things live

- `week-1/main.py` — FastAPI app: `/agent` (function-tool transport), `/agent/mcp` (MCP transport), `/eval` and `/eval/dataset`, `/memory*` endpoints.
- `week-1/rag_core.py` — RAG retrieval + `Answer` schema + citation guard. Corpus is scoped to `ONCALL_DOCUMENT_IDS` (computed from `knowledge_base/` at import) via a Pinecone metadata filter — don't query the index without that filter or you'll pull in unrelated documents from other exercises sharing the same index.
- `week-1/memory_store.py` / `week-1/memory_cli.py` — durable human-memory store, Pinecone `"memory"` namespace, separate from the RAG `default` namespace.
- `week-1/rag_ui.py` — Streamlit UI (`Ingest`, `Ask`, `Debug Retrieve`, `Agent`, `Eval`, `Memory` tabs).
- Live: API `https://ai-internship-5euv.onrender.com`, UI `https://ai-internship-streamlit-ui.onrender.com`.
