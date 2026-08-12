#!/usr/bin/env python3
"""
Ingests the full Northwind sample doc pack into the running /ingest API.

For each file: reads its text, assigns the stable document_id defined in the
dataset's own README (northwind-sample-docs/README.md), POSTs to /ingest, and
prints the chunk count. Prints the total vector count in the store at the end.

Run: python ingest_northwind_docs.py
Requires the API server already running at API_BASE (default localhost:8000).
"""

import sys
from pathlib import Path

import httpx

API_BASE = "http://127.0.0.1:8000"
DOCS_DIR = (
    Path(__file__).resolve().parent.parent
    / "week-2" / "rag-vector-databases" / "northwind-sample-docs"
)

# document_id -> filename, per northwind-sample-docs/README.md
DOCUMENTS = {
    "POL-101": "doc1_handbook.txt",
    "POL-114": "doc2_expenses.txt",
    "POL-207": "doc3_security.txt",
    "SPEC-WB9": "doc4_product.txt",
    "POL-220": "doc5_it_acceptable_use.txt",
    "POL-118": "doc6_facilities.txt",
}


def main() -> int:
    total_chunks_this_run = 0

    for document_id, filename in DOCUMENTS.items():
        path = DOCS_DIR / filename
        if not path.exists():
            print(f"SKIP  {document_id} ({filename}) -- file not found at {path}")
            continue

        text = path.read_text(encoding="utf-8")
        response = httpx.post(
            f"{API_BASE}/ingest",
            json={"text": text, "document_id": document_id, "source": filename},
            timeout=60.0,
        )

        if response.status_code != 200:
            print(f"FAIL  {document_id} ({filename}) -- HTTP {response.status_code}: {response.text}")
            continue

        data = response.json()
        chunks = data["chunks_indexed"]
        total_chunks_this_run += chunks
        print(f"OK    {document_id} ({filename}) -- {chunks} chunks indexed")

    print(f"\nChunks indexed this run: {total_chunks_this_run}")

    stats = httpx.get(f"{API_BASE}/debug/pinecone", timeout=10.0).json()
    print(f"Total chunks in vector store: {stats.get('total_vector_count', 'unknown')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
