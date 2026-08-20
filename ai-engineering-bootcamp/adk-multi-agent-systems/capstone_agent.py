"""
Capstone Agent: On-Call Runbook Triage (single agent, placeholder tool)

Patterns copied from demo1_routing.py in this same folder:
  - Agent(...) construction shape (name, model, instruction, tools)
  - The async ask()/main() runner shape (InMemorySessionService + Runner + run_async)
  - MODEL constant + load_dotenv() at the top

What's different from demo1_routing.py, on purpose:
  - Only ONE Agent, no sub_agents/router -- this job is single-domain (on-call
    incident triage against one knowledge base), so a router would be
    complexity with no job to do yet. Add routing later only if a second,
    genuinely distinct specialty shows up (see week 1 README/JD-mapping notes).
  - tools=[search_runbooks] is a PLACEHOLDER. It returns a stub response so
    you can see the real Think -> Act -> Observe loop happen end to end
    before wiring it to the live capstone API
    (https://ai-internship-5euv.onrender.com/ask). That wiring is the next step.
  - run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS) caps how many model
    calls a single run can make, so a confused loop can't run forever.
  - Every event is logged with an explicit [THINK]/[ACT]/[OBSERVE]/[FINAL]
    tag, read directly off the event's real fields (function_call /
    function_response / thought / text) -- not inferred or guessed.

Run:
  python capstone_agent.py

(adk web is also an option since root_agent is defined at module level, but
this Python entrypoint is what's actually been tested here, same as the demos.)
"""

import asyncio

import httpx
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv()

MODEL = "gemini-3.6-flash"

# Live capstone API (Session 1/2 FastAPI service, deployed on Render).
CAPSTONE_ASK_URL = "https://ai-internship-5euv.onrender.com/ask"

# Hard cap on model calls in a single run. Small on purpose: this job should
# resolve in a couple of turns (decide to search -> read result -> answer).
# If a run ever hits this limit, that's a signal something is looping wrong,
# not a knob to raise casually.
MAX_LLM_CALLS = 6


# --- Tools ---

def search_runbooks(question: str) -> dict:
    """Search the on-call runbook/postmortem knowledge base for information
    relevant to this incident question.

    Real tool: calls POST /ask on the live capstone RAG API, which embeds
    the question, retrieves matching chunks from Pinecone, and returns a
    grounded answer with citations -- or an honest refusal if nothing
    relevant was found. This is a genuine network call against production
    data, not a stub.

    Returns a dict with either the real answer fields (answer,
    sources_needed, citations, retrieved_chunk_ids) or an "error" key if
    the request itself failed -- the caller must check for "error" and
    surface it rather than treat a failed call as a successful empty result.
    """
    try:
        response = httpx.post(CAPSTONE_ASK_URL, json={"question": question}, timeout=60.0)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return {
            "error": f"Runbook API returned HTTP {exc.response.status_code}",
            "detail": exc.response.text[:500],
        }
    except httpx.HTTPError as exc:
        return {"error": f"Request to runbook API failed: {exc}"}

    data = response.json()
    answer = data["answer"]
    return {
        "answer": answer["answer"],
        "sources_needed": answer["sources_needed"],
        "citations": answer["citations"],
        "retrieved_chunk_ids": data["retrieved_chunk_ids"],
    }


# --- Agent ---
# name / model / instruction with an explicit goal, constraints, and a
# definition of "done" -- required shape per the assignment brief.

root_agent = Agent(
    name="oncall_runbook_agent",
    model=MODEL,
    instruction=(
        "You are an on-call incident-triage agent for a Shopify-platform engineering team.\n\n"
        "GOAL: given a description of a production symptom, use the search_runbooks tool "
        "to find the matching runbook or postmortem, then return specific diagnostic and "
        "remediation steps, citing the source document.\n\n"
        "CONSTRAINTS: never invent a runbook, root cause, or remediation step that the tool "
        "did not actually return. If the tool result has an 'error' key, the search itself "
        "failed -- tell the user the lookup failed and why, do not guess an answer instead. "
        "If sources_needed is true, the knowledge base did not have enough information -- "
        "say so honestly rather than filling the gap with your own knowledge.\n\n"
        "DONE: you have either (a) returned diagnostic steps grounded in the tool's real "
        "answer with its citations, (b) told the user the knowledge base had no match "
        "(sources_needed: true), or (c) told the user the tool call itself failed (error key)."
    ),
    tools=[search_runbooks],
)


# --- Runner with Think/Act/Observe logging ---

def log_event(step: int, event) -> None:
    """Prints one labeled line per meaningful part of an event.
    Tag comes directly from which real field is populated on the part --
    function_call = Act, function_response = Observe, thought = Think,
    plain text = Think (intermediate) or Final (last event of the run).
    """
    if not event.content or not event.content.parts:
        return
    author = event.author or "agent"
    is_final = event.is_final_response()

    for part in event.content.parts:
        if part.function_call:
            print(f"[{step:02d}] ACT     {author} -> {part.function_call.name}({dict(part.function_call.args or {})})")
        elif part.function_response:
            print(f"[{step:02d}] OBSERVE {author} <- {part.function_response.name} returned: {part.function_response.response}")
        elif getattr(part, "thought", None):
            print(f"[{step:02d}] THINK   {author}: {part.text}")
        elif part.text:
            label = "FINAL" if is_final else "THINK"
            print(f"[{step:02d}] {label:<7} {author}: {part.text}")


async def ask(agent: Agent, message: str) -> str:
    service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="capstone_agent", session_service=service)
    session = await service.create_session(app_name="capstone_agent", user_id="user1")
    content = types.Content(role="user", parts=[types.Part(text=message)])

    run_config = RunConfig(max_llm_calls=MAX_LLM_CALLS)
    final_text = "(no response)"
    step = 0

    async for event in runner.run_async(
        user_id="user1",
        session_id=session.id,
        new_message=content,
        run_config=run_config,
    ):
        step += 1
        log_event(step, event)
        if event.is_final_response() and event.content and event.content.parts:
            final_text = event.content.parts[0].text

    return final_text


async def main() -> None:
    # The live Pinecone index now holds the real Shopify runbook/postmortem
    # corpus (Maven AI Bootcamp/data/{runbooks,postmortems}), matching the
    # agent's actual on-call domain. This exact scenario is covered by
    # postmortem_2026-04-18_storefront_search_latency_spike.md and
    # runbook_redis_cache_stampede.md.
    query = (
        "Storefront search p99 latency spiked to 3 seconds and no deploy correlates. "
        "What's going on and what should I check?"
    )
    print(f"User: {query}\n")
    answer = await ask(root_agent, query)
    print(f"\nFinal answer:\n{answer}")


if __name__ == "__main__":
    asyncio.run(main())
