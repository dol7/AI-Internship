# What my eval suite caught (and what I got wrong before it did)

*Designed version with the actual before/after eval screenshots embedded: [**"The 54% Bug"**](https://claude.ai/code/artifact/6f1986d4-70ea-4ac3-a2aa-d56b7d9ff242). This file is the source of record; that page is the shareable, illustrated read.*

I built an AI on-call assistant — it answers incident questions grounded in a team's real runbooks and postmortems, and it's supposed to cite exactly which document it used. Live demo: [ai-internship-streamlit-ui.onrender.com](https://ai-internship-streamlit-ui.onrender.com). This is the story of the one failure that mattered most, and the two times I fixed it wrong before I fixed it right.

## The failure

The agent returns a structured object: an answer, a `sources_needed` flag (did I actually need evidence for this?), and a list of `citations` (which documents I used). The rule should be simple — if `sources_needed` is true, there had better be citations backing it up.

I found the failure the boring way: I open-coded 20 sample traces plus 15+ of my own capstone runs, writing free-text notes before touching any metric. No shortcuts, no scoring until the notes were done. Out of that came a failure taxonomy with four-plus categories, ranked by frequency times impact. The winner, by a clear margin: the agent would sometimes say `sources_needed: true` and then either omit citations or attach them inconsistently. Not a hallucination exactly — a broken promise. The model was telling me it needed evidence and then not showing its work.

## Fix attempt #1: a checklist in the prompt

Obvious first move — tell the model more clearly what's expected. I added a three-part checklist to the prompt: state whether sources are needed, list them if so, don't claim you have them if you don't. Re-ran the eval. Real improvement, not fake — but not clean. Some runs still slipped through.

## Fix attempt #2: a stricter two-gate rewrite

I tightened the prompt further — two explicit gates the model had to reason through before answering. Better again. Still not reliable across repeated runs on the same questions. That inconsistency itself was the tell: if the same prompt against the same questions gives different pass rates from run to run, you're not looking at a bug you can prompt your way out of. You're looking at sampling variance in a model that doesn't reliably follow instructions on every draw.

## The actual fix: move the guarantee into code

If citation correctness matters, don't ask the model to police itself — check it, in code, and enforce it deterministically. The fix ended up being almost embarrassingly small: after the model responds, if `sources_needed` is true and the consistency check on `citations` fails, clear the citations and flag it, full stop. No amount of prompt engineering can be more reliable than a real `if` statement.

## The number

I re-ran the same 13 real questions before and after, with a flag (`DEMO_DISABLE_CITATION_GUARD`) that lets me toggle the old prompt-only behavior back on for comparison. Prompt-only: `sources_needed_citation_consistency` landed between 54% and 69% depending on the run — real variance, not a cherry-picked bad sample. Code-level fix: **13 out of 13, 100%**, and it has stayed there on every run since, including one I ran again the same day I'm writing this.

## What I'd tell someone starting their own eval suite

Two things. First: open-code before you build metrics. I would not have found this failure by staring at a dashboard — I found it by reading transcripts and writing down what actually happened, in plain language, before I let myself count anything. Second: if a fix's success rate depends on which run you happened to look at, it isn't fixed. A prompt can nudge a model. It can't guarantee it. For anything you actually need to be true every time, put the guarantee in code and let the model do the parts only a model can do.

Full writeup, architecture, and the rest of the eval story: [README.md § Capstone](https://github.com/dol7/AI-Internship/blob/main/ai-engineering-bootcamp-v2/week-1/README.md#capstone-on-call-incident-triage-agent).
