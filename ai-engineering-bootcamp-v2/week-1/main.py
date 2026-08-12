"""Week 1 live demo — five stages in one file, built up live in class.

Session 2 extension: /ask is now RAG-grounded (retrieves from Pinecone before
answering, cites sources, refuses when nothing relevant is found), and /ingest
lets you add documents to the knowledge base it retrieves from.
"""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from pydantic import BaseModel, Field, ValidationError

# Load .env from this folder so the key is found regardless of shell working directory.
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

# Reuse one client so TLS handshakes are not repeated on every request.
app = FastAPI()
client = OpenAI()  # Reads OPENAI_API_KEY from the environment; never hardcode keys.

# Stage 4 default — strong general model; swap at request time for the live demo.
DEFAULT_MODEL = "gpt-4o"

# Stage 5 — per-1K-token input/output USD (derived from OpenAI list prices).
MODEL_PRICES_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "o3-mini": (0.0011, 0.0044),
}

# Session 2 — retrieval config.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSION = 1536  # must match EMBEDDING_MODEL's output size if that's overridden
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "week1-rag-documents")
RETRIEVAL_TOP_K = 5
RETRIEVAL_SCORE_THRESHOLD = 0.35  # below this, a chunk doesn't count as "relevant"
# Calibrated empirically: irrelevant queries scored ~0.00, a loose paraphrase of
# an actually-relevant chunk scored ~0.50, a close topical match scored ~0.67.
# 0.75 (the original guess) was cutting off real matches; 0.35 sits safely
# below genuine relevance and well above noise.
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "400"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "80"))
# Originally 800/100 per spec; dropped to 400/80 after live-testing against the
# Northwind handbook showed 800 merged distinct subsections into one chunk,
# diluting embeddings enough that an unrelated chunk narrowly outranked the
# actually-relevant one for "how many remote days are allowed?" (0.506 vs 0.493).
# At 400/80 the relevant chunk isolates cleanly and wins by a real margin (0.589 vs 0.551).

pinecone_client = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
_existing_indexes = [idx["name"] for idx in pinecone_client.list_indexes()]
if PINECONE_INDEX_NAME not in _existing_indexes:
    pinecone_client.create_index(
        name=PINECONE_INDEX_NAME,
        dimension=EMBEDDING_DIMENSION,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1"),
    )
    while not pinecone_client.describe_index(PINECONE_INDEX_NAME).status["ready"]:
        time.sleep(1)
pinecone_index = pinecone_client.Index(PINECONE_INDEX_NAME)


class Answer(BaseModel):
    """Structured model output — this is what turns a chatbot into a component."""

    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    sources_needed: bool  # true when the retrieved context did not contain the answer
    citations: list[str] = Field(default_factory=list)  # source labels actually used


class AskRequest(BaseModel):
    """Typed request body so bad input is rejected before we spend tokens."""

    question: str
    force_bad: bool = False  # Stage 3 demo knob — first attempt breaks schema on purpose.
    model: str | None = None  # Stage 4 — optional override to swap models live.


class AskResponse(BaseModel):
    """Typed response so callers always get the same shape back."""

    answer: Answer
    tokens_used: int
    model: str
    latency_ms: int
    cost_usd: float
    retrieved_chunk_ids: list[str] = Field(default_factory=list)  # actual vector IDs retrieved, independent of what the model chose to cite


class IngestRequest(BaseModel):
    """One document at a time. document_id is the stable identifier callers
    use to reference this document later; source is optional descriptive
    metadata (e.g. an original filename) shown back in citations."""

    text: str
    document_id: str = Field(min_length=1)
    source: str | None = None


class IngestResponse(BaseModel):
    document_id: str
    chunks_indexed: int
    status: str


class RetrievedChunk(BaseModel):
    chunk_id: str  # matches the vector ID used at ingest: f"{document_id}-{chunk_index}"
    text: str
    document_id: str
    chunk_index: int
    source: str | None
    score: float
    passes_threshold: bool


class DebugRetrieveResponse(BaseModel):
    question: str
    threshold: float
    chunks: list[RetrievedChunk]


def compute_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Turn real usage into dollars — same prompt, different model, different cost."""

    prices = MODEL_PRICES_PER_1K.get(model, MODEL_PRICES_PER_1K[DEFAULT_MODEL])
    input_per_1k, output_per_1k = prices
    return (prompt_tokens / 1000 * input_per_1k) + (completion_tokens / 1000 * output_per_1k)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """LangChain's RecursiveCharacterTextSplitter — tries to split on paragraph,
    then line, then word boundaries before falling back to a hard character cut."""

    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=overlap)
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]


def retrieve_all(question: str, top_k: int = RETRIEVAL_TOP_K) -> list[RetrievedChunk]:
    """
    Embed the question, search Pinecone, return every match with its raw score
    and whether it would clear RETRIEVAL_SCORE_THRESHOLD — unfiltered, so this
    is the one place to look when deciding if the threshold needs recalibrating.
    """

    embedding = client.embeddings.create(model=EMBEDDING_MODEL, input=question).data[0].embedding
    results = pinecone_index.query(vector=embedding, top_k=top_k, include_metadata=True)

    return [
        RetrievedChunk(
            chunk_id=match["id"],
            text=match["metadata"]["text"],
            document_id=match["metadata"]["document_id"],
            chunk_index=match["metadata"]["chunk_index"],
            source=match["metadata"].get("source"),
            score=match["score"],
            passes_threshold=match["score"] >= RETRIEVAL_SCORE_THRESHOLD,
        )
        for match in results["matches"]
    ]


def retrieve_context(question: str, top_k: int = RETRIEVAL_TOP_K) -> list[RetrievedChunk]:
    """
    Session 2 center: same as retrieve_all, but keeps only chunks that actually
    clear the relevance threshold. An empty result here is what drives the
    refusal path in call_rag_structured — it is not an error case.
    """

    return [chunk for chunk in retrieve_all(question, top_k) if chunk.passes_threshold]


def build_rag_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    """
    Force the model to answer only from the provided context, and to refuse
    (rather than guess) when nothing relevant was retrieved.
    """

    if not chunks:
        return (
            f"Question: {question}\n\n"
            "No relevant documents were found in the knowledge base for this question. "
            "You must refuse to answer from your own knowledge. Set sources_needed to true, "
            "citations to an empty list, and explain in the answer field that the knowledge "
            "base does not contain information to answer this question."
        )

    context_block = "\n\n".join(
        f"[document_id: {c.document_id}]\n{c.text}" for c in chunks
    )
    return (
        f"Context from the knowledge base:\n{context_block}\n\n"
        f"Question: {question}\n\n"
        "Answer ONLY using the context above — do not use outside knowledge. "
        "If the context does not fully answer the question, say so explicitly and set "
        "sources_needed to true. In the citations field, list the document_id of every "
        "chunk you actually used to answer (one entry per document_id, no duplicates)."
    )


def call_rag_structured(question: str, model: str) -> tuple[Answer, int, int, int, list[str]]:
    """
    Stage 2 pattern (OpenAI structured output) extended with retrieval:
    retrieve first, then force the answer into the Answer schema grounded in
    whatever context (if any) was found. Also returns the actual retrieved
    chunk IDs, independent of which ones the model chose to cite.
    """

    chunks = retrieve_context(question)
    prompt = build_rag_prompt(question, chunks)

    completion = client.chat.completions.parse(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format=Answer,
    )

    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("Model returned no parseable structured output")

    usage = completion.usage
    total = usage.total_tokens if usage else 0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    retrieved_chunk_ids = [c.chunk_id for c in chunks]
    return parsed, total, prompt_tokens, completion_tokens, retrieved_chunk_ids


def call_model_unsafe(question: str, model: str) -> tuple[Answer, int, int, int]:
    """
    Stage 3 demo path: free-form JSON call, then validate locally.
    The bad instruction makes confidence a string so Pydantic rejects it reliably.
    Unchanged from Session 1 — force_bad is a schema-guardrail demo, orthogonal to retrieval.
    """

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{question}\n\n"
                    "Reply with ONLY a JSON object using keys answer, confidence, sources_needed, citations. "
                    "Set confidence to the string 'very high' (not a number)."
                ),
            }
        ],
    )

    raw = completion.choices[0].message.content or ""
    # Guardrail: refuse malformed output instead of passing it through to clients.
    answer = Answer.model_validate_json(raw)

    usage = completion.usage
    total = usage.total_tokens if usage else 0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    return answer, total, prompt_tokens, completion_tokens


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug/pinecone")
def debug_pinecone() -> dict[str, str | int | bool]:
    """
    Isolated connectivity check — talks to Pinecone only, no OpenAI call, no
    embedding, no cost. Confirms the API key is valid and the index is reachable.
    Use this (not /debug/retrieve) when the question is just "is Pinecone up?".
    """

    try:
        stats = pinecone_index.describe_index_stats()
        return {
            "reachable": True,
            "index_name": PINECONE_INDEX_NAME,
            "total_vector_count": stats["total_vector_count"],
        }
    except Exception as exc:
        return {"reachable": False, "index_name": PINECONE_INDEX_NAME, "error": str(exc)}


@app.get("/debug/retrieve")
def debug_retrieve(q: str, top_k: int = 5) -> DebugRetrieveResponse:
    """
    Verify retrieval before wiring generation. No LLM call — just embeds the
    question, queries Pinecone, and returns the top-k matches with their raw
    similarity scores, document_id, and whether each clears RETRIEVAL_SCORE_THRESHOLD.

    curl -s "http://127.0.0.1:8000/debug/retrieve?q=your+question+here"
    """

    return DebugRetrieveResponse(
        question=q,
        threshold=RETRIEVAL_SCORE_THRESHOLD,
        chunks=retrieve_all(q, top_k),
    )


@app.post("/ingest")
def ingest(body: IngestRequest) -> IngestResponse:
    """
    Chunk, embed, and upsert one document into the knowledge base /ask retrieves from.

    curl -X POST http://127.0.0.1:8000/ingest \
      -H "Content-Type: application/json" \
      -d '{
            "text": "Our return policy allows returns within 30 days...",
            "document_id": "return-policy-v1",
            "source": "return-policy.pdf"
          }'
    """

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty.")

    chunks = chunk_text(body.text)
    if not chunks:
        raise HTTPException(status_code=400, detail="No content to ingest after chunking.")

    embeddings = client.embeddings.create(model=EMBEDDING_MODEL, input=chunks).data
    vectors = [
        {
            "id": f"{body.document_id}-{i}",
            "values": embeddings[i].embedding,
            "metadata": {
                "text": chunk,
                "document_id": body.document_id,
                "chunk_index": i,
                **({"source": body.source} if body.source else {}),
            },
        }
        for i, chunk in enumerate(chunks)
    ]
    pinecone_index.upsert(vectors=vectors)

    return IngestResponse(document_id=body.document_id, chunks_indexed=len(chunks), status="ok")


@app.post("/ask")
def ask(body: AskRequest) -> AskResponse:
    """Answer one question, grounded in retrieved context, with guardrails and cost visibility."""

    model = body.model or DEFAULT_MODEL
    last_error: str | None = None

    # Stage 3: one retry keeps the logic legible while still protecting callers.
    for attempt in range(2):
        try:
            start = time.perf_counter()

            # First attempt with force_bad uses the unsafe path; retry uses the RAG path.
            use_bad_path = body.force_bad and attempt == 0
            if use_bad_path:
                # No retrieval on this path — it deliberately skips RAG to demo the guardrail.
                answer, tokens_used, prompt_tokens, completion_tokens = call_model_unsafe(
                    body.question, model
                )
                retrieved_chunk_ids: list[str] = []
            else:
                answer, tokens_used, prompt_tokens, completion_tokens, retrieved_chunk_ids = (
                    call_rag_structured(body.question, model)
                )

            latency_ms = int((time.perf_counter() - start) * 1000)
            cost_usd = compute_cost_usd(model, prompt_tokens, completion_tokens)

            return AskResponse(
                answer=answer,
                tokens_used=tokens_used,
                model=model,
                latency_ms=latency_ms,
                cost_usd=round(cost_usd, 6),
                retrieved_chunk_ids=retrieved_chunk_ids,
            )
        except (ValidationError, ValueError) as exc:
            last_error = str(exc)
            continue

    # Clean failure — never leak a half-parsed response to the client.
    raise HTTPException(
        status_code=502,
        detail=f"Model response failed schema validation after retry: {last_error}",
    )
