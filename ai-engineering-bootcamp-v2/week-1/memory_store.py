"""Durable human-memory store for the on-call agent.

Stores stable user preferences and project facts -- corrections given once
that should apply going forward, last-successful-fix notes, escalation
routing preferences. Explicitly NOT for ephemeral tool output: raw
search_runbooks() results, retrieved_chunk_ids, one-off diagnostic text --
all regeneratable per-request, none of it belongs in long-term memory.

Backend: a dedicated Pinecone namespace ("memory") in the same index the
RAG knowledge base already uses (rag_core.pinecone_index), not a separate
service. Chosen specifically because it survives Render's free-tier
ephemeral filesystem (a plain SQLite/JSON file on local disk does NOT --
verified against Render's own docs: local files are wiped on every restart
or redeploy on the free tier) without requiring a new external account.
Vectors are dummy (all-zero) -- this is used purely as a key/value store via
fetch/upsert/delete/list, never similarity search, so the embedding
machinery is irrelevant here; only the metadata payload matters.
"""

import re
from datetime import datetime, timezone

from openai import OpenAI as _RawOpenAI  # gate classifier does not need Langfuse wrapping
from pydantic import BaseModel, Field

from rag_core import EMBEDDING_DIMENSION, pinecone_index

MEMORY_NAMESPACE = "memory"
# Pinecone rejects all-zero dense vectors ("must contain at least one
# non-zero value") -- this store never does similarity search, so the
# actual value doesn't matter, just that it's a valid non-zero vector.
_DUMMY_VECTOR = [1e-6] * EMBEDDING_DIMENSION

_gate_client = _RawOpenAI()
GATE_MODEL = "gpt-4o-mini"  # cheap classifier call, not the main answer model


def _slugify_key(key: str) -> str:
    """Normalize any key to a Pinecone-safe vector ID.

    Found by real testing against live Pinecone, not from docs: a vector ID
    containing a space upserts with upserted_count=1 (reports success) but
    is then never fetchable by that exact ID -- silently unreadable, not an
    error. Reproduced directly against the SDK, independent of this app's
    code. The gate classifier's LLM-proposed keys aren't guaranteed to be
    space-free (e.g. "db escalation rule"), so every entry point funnels
    through this before touching Pinecone.
    """

    slug = re.sub(r"[^a-z0-9]+", "-", key.strip().lower()).strip("-")
    return slug or "untitled"


class MemoryFact(BaseModel):
    key: str
    value: str
    category: str  # "correction" | "preference" | "last_successful_fix" | "escalation_rule" | "other"
    written_at: str


class GateDecision(BaseModel):
    """Structured output for the write gate -- mirrors the Answer pattern
    already used elsewhere in this codebase (rag_core.Answer)."""

    should_persist: bool
    reason: str = Field(description="One-sentence explanation of the decision, for the caller to see")
    key: str | None = Field(default=None, description="A short, stable slug for this fact, e.g. 'redis-stampede-note'")
    value: str | None = Field(default=None, description="The distilled durable fact/preference itself, not the raw input")
    category: str | None = Field(default=None, description="One of: correction, preference, last_successful_fix, escalation_rule, other")


GATE_PROMPT = (
    "You decide whether a piece of text is worth persisting to long-term memory "
    "for an on-call incident-triage agent, or whether it should be discarded.\n\n"
    "PERSIST (should_persist=true) only if the text is one of:\n"
    "- A correction or standing rule the user is giving for future incidents "
    "(e.g. 'always check the coalescing flag first for cache stampedes')\n"
    "- A note about which fix actually worked last time for a specific incident type\n"
    "- A stable preference, such as which team to escalate a category of incident to\n\n"
    "DISCARD (should_persist=false) if the text is:\n"
    "- A one-off question or incident description with no standing rule in it\n"
    "- Raw tool output, retrieved document text, or a diagnostic answer -- "
    "regeneratable, not something a human needs remembered\n"
    "- Small talk, or anything not stable/durable across future sessions\n\n"
    "If persisting, distill the text into a short, clean value (not verbatim raw "
    "input) and propose a short stable key. If discarding, leave key/value/category null.\n\n"
    f"Text: {{text}}"
)


def gate_and_write(text: str) -> GateDecision:
    """Classify text; write to memory only if it passes the gate. Always
    returns the decision (including discards) so the caller can show why."""

    completion = _gate_client.chat.completions.parse(
        model=GATE_MODEL,
        messages=[{"role": "user", "content": GATE_PROMPT.format(text=text)}],
        response_format=GateDecision,
    )
    decision = completion.choices[0].message.parsed
    if decision is None:
        return GateDecision(should_persist=False, reason="Gate classifier returned no parseable output.")

    if decision.should_persist and decision.key and decision.value:
        memory_replace(decision.key, decision.value, decision.category or "other")

    return decision


def memory_replace(key: str, value: str, category: str = "other") -> MemoryFact:
    """Direct, ungated write -- upsert is inherently replace-if-exists.
    Used by gate_and_write() and available directly for the CLI/admin path."""

    slug = _slugify_key(key)
    fact = MemoryFact(key=slug, value=value, category=category, written_at=datetime.now(timezone.utc).isoformat())
    pinecone_index.upsert(
        vectors=[
            {
                "id": slug,
                "values": _DUMMY_VECTOR,
                "metadata": {"value": fact.value, "category": fact.category, "written_at": fact.written_at},
            }
        ],
        namespace=MEMORY_NAMESPACE,
    )
    return fact


def memory_get(key: str) -> MemoryFact | None:
    slug = _slugify_key(key)
    result = pinecone_index.fetch(ids=[slug], namespace=MEMORY_NAMESPACE)
    vectors = result.vectors if hasattr(result, "vectors") else result.get("vectors", {})
    if slug not in vectors:
        return None
    meta = vectors[slug].metadata
    return MemoryFact(key=slug, value=meta["value"], category=meta["category"], written_at=meta["written_at"])


def memory_list() -> list[MemoryFact]:
    keys = []
    for batch in pinecone_index.list(namespace=MEMORY_NAMESPACE):
        for item in batch:
            keys.append(item.id if hasattr(item, "id") else item)
    if not keys:
        return []
    result = pinecone_index.fetch(ids=keys, namespace=MEMORY_NAMESPACE)
    vectors = result.vectors if hasattr(result, "vectors") else result.get("vectors", {})
    return [
        MemoryFact(key=k, value=v.metadata["value"], category=v.metadata["category"], written_at=v.metadata["written_at"])
        for k, v in vectors.items()
    ]


def memory_delete(key: str) -> None:
    pinecone_index.delete(ids=[_slugify_key(key)], namespace=MEMORY_NAMESPACE)
