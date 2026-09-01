# Interview talking points — three decisions, one breath each

Each is structured **decision → why → evidence**, so it stands on its own without slides.

## 1. Moved the citation guard from the prompt to the code

**Decision:** Instead of relying on the model to self-police citations, `rag_core.py` now deterministically clears citations whenever the model's own `sources_needed`/`citations` fields are inconsistent.

**Why:** Two rounds of prompt-only fixes (a checklist, then a stricter two-gate rewrite) each showed real but incomplete, variance-prone improvement. A grounding guarantee shouldn't depend on the model reliably following instructions on every sample.

**Evidence:** Re-ran the same 13 real questions before and after. Prompt-only (guard off): 54–69% consistency across runs — genuine sampling variance, not a single bad draw. Code-level fix (guard on): 13/13, 100%, on every run since, including a fresh check today.

## 2. Found and fixed a silent Pinecone bug in the memory store, live, not in a test environment

**Decision:** Sanitize every memory key into a slug before it becomes a Pinecone vector ID, applied consistently across write/read/delete.

**Why:** Testing the deployed memory endpoint for real (not just locally) surfaced that Pinecone accepts a vector ID containing a space — `upserted_count=1`, no error — but that vector is then permanently unfetchable by that exact ID. The gate classifier's LLM-proposed keys aren't guaranteed to be space-free, so this was a live, real bug, not a hypothetical.

**Evidence:** Reproduced directly against the Pinecone SDK, independent of any of my endpoint code, isolating it from a plausible alternative explanation (eventual-consistency lag, which I'd already ruled out by comparison against a dash-only key that worked immediately). Shipped the fix, then re-verified the exact failing case live before calling it done.

## 3. Root-caused a production-only MCP failure from logs, not guesses

**Decision:** Pass `env=os.environ.copy()` into `StdioServerParameters` when spawning the MCP subprocess.

**Why:** `/agent/mcp` returned 502 in production while working locally. Two earlier hypotheses (subprocess spawn too slow on Render's free CPU; timeout/call-budget too tight) were tested and ruled out — the first was real but insufficient, the second didn't move the failure rate at all. The actual cause, found in real Render logs: `OpenAIError: Missing credentials` inside the subprocess, because `StdioServerParameters` does not auto-inherit the parent process's environment. It never showed up locally because a `.env` file on disk masked it there — Render has no such file; secrets come from real env vars that don't propagate to a child process by default.

**Evidence:** Confirmed live after the fix — `/agent/mcp` returns 200 with a grounded, cited answer, same as the direct function-tool path.
