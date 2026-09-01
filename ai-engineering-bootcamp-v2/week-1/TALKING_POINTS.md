# Interview talking points — three decisions, one breath each

Three specific decisions, not a feature list. Each is **decision → why → evidence**, sized to say in one breath.

## 1. Why an agent, not a fixed workflow

**Decision:** Built this as an agent — Google ADK `Agent`/`Runner` deciding at runtime whether to call `search_runbooks` at all, and how many times — instead of a fixed retrieve-then-generate pipeline.

**Why:** the tradeoff is predictability and cost versus correctness. A fixed pipeline is cheaper, faster, and fully deterministic — one retrieval call, every time — but a single fixed query can't cover a genuinely compound or ambiguous incident description. Accepted variable latency/cost, capped by a `max_llm_calls` budget rather than left unbounded, in exchange for handling the harder questions correctly.

**Evidence:** on a real compound question, the agent issued two sequential tool calls with different queries before answering — on its own. Nothing in the code fixes the call count or sequence; it's bounded, not scripted.

## 2. What evals caught that I didn't expect

**Decision:** Stopped trusting reparsed trace exports for eval verification and switched to calling the real retrieval function directly (or regenerating a clean dataset) for every before/after measurement.

**Why:** the tradeoff was eval-build speed versus eval validity — reparsing existing trace logs is faster than rebuilding clean data, but only if the reparse is actually trustworthy.

**Evidence:** my first before/after test came back a suspiciously clean 26/26. Traced it to a bare `except: pass` silently swallowing a failed reparse of a 300-character-truncated tool observation, defaulting the very field I was testing to a false value instead of raising. It only surfaced because the methodology itself got challenged — "agreement is the trap metric, an always-pass judge gets high agreement and zero true-positive rate" — not because I caught it myself. Every eval after that called the live function directly instead of trusting exported text.

## 3. A memory tradeoff I chose deliberately

**Decision:** Gate memory writes through a small classifier (`gpt-4o-mini`) rather than writing everything, or requiring an explicit "remember this" command.

**Why:** the tradeoff is recall versus precision of what gets remembered. Write-everything pollutes memory with ephemeral tool output and one-off questions; require-an-explicit-command misses facts stated in passing and adds friction. The gate accepts occasional misclassification in exchange for mostly-correct behavior with zero extra user effort.

**Evidence:** tested against three real cases — a genuine correction persisted with a distilled key/value, a one-off question discarded, raw tool-output-shaped text discarded — confirmed both in local testing and live against the deployed API this session, not just a unit test.
