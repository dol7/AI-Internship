"""Minimal Streamlit UI for the live RAG service (POST /ingest, POST /ask).

Thin client only. All chunking, embedding, retrieval, and generation happen
in the FastAPI service -- this page just calls its two endpoints over HTTP
and displays the response. No OpenAI/Pinecone calls, no RAG logic here.

Run:
  streamlit run rag_ui.py

Points at your API via the sidebar "API base URL" field, which defaults to
the API_BASE_URL environment variable if set (falls back to localhost).
No secrets live in this UI -- the API holds its own OpenAI/Pinecone keys
server-side; this page only ever needs a URL.
"""

import os

import httpx
import streamlit as st

st.set_page_config(page_title="RAG Service UI", layout="wide")
st.title("RAG Service — Ingest & Ask")
st.caption("Thin client only. All RAG logic (chunking, retrieval, generation) lives in the API.")

default_base_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
base_url = st.sidebar.text_input("API base URL", value=default_base_url).rstrip("/")
st.sidebar.caption(
    "Defaults to the API_BASE_URL environment variable if set. "
    "No secrets are stored here -- the API holds its own keys server-side."
)

tab_ingest, tab_ask, tab_debug = st.tabs(["Ingest", "Ask", "Debug Retrieve"])

with tab_ingest:
    st.subheader("POST /ingest")
    text = st.text_area("Text to ingest", height=220, placeholder="Paste document text here...")
    document_id = st.text_input("document_id", placeholder="e.g. handbook-v1")
    source = st.text_input("source (optional)", placeholder="e.g. handbook.pdf")

    if st.button("Ingest", type="primary"):
        if not text.strip() or not document_id.strip():
            st.error("text and document_id are both required.")
        else:
            payload = {"text": text, "document_id": document_id}
            if source.strip():
                payload["source"] = source
            try:
                response = httpx.post(f"{base_url}/ingest", json=payload, timeout=60.0)
            except httpx.HTTPError as exc:
                st.error(f"Request failed: {exc}")
            else:
                if response.status_code == 200:
                    st.success("Ingested successfully")
                    st.json(response.json())
                else:
                    st.error(f"HTTP {response.status_code}")
                    st.json(response.json())

with tab_ask:
    st.subheader("POST /ask")
    question = st.text_input("Question", placeholder="Ask something covered by your ingested docs...")

    if st.button("Ask", type="primary"):
        if not question.strip():
            st.error("Question is required.")
        else:
            try:
                response = httpx.post(f"{base_url}/ask", json={"question": question}, timeout=60.0)
            except httpx.HTTPError as exc:
                st.error(f"Request failed: {exc}")
            else:
                if response.status_code != 200:
                    st.error(f"HTTP {response.status_code}")
                    st.json(response.json())
                else:
                    data = response.json()
                    answer = data["answer"]

                    if answer.get("sources_needed"):
                        st.warning(
                            "⚠️ REFUSED — the knowledge base did not contain enough "
                            "information to answer this question."
                        )
                    else:
                        st.success("✅ Answered from retrieved context")

                    st.markdown(f"**Answer:** {answer['answer']}")

                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Citations** _(model-reported)_")
                        if answer.get("citations"):
                            for c in answer["citations"]:
                                st.markdown(f"- `{c}`")
                        else:
                            st.markdown("_(none)_")
                    with col2:
                        st.markdown("**Retrieved chunk IDs** _(ground truth)_")
                        if data.get("retrieved_chunk_ids"):
                            for cid in data["retrieved_chunk_ids"]:
                                st.markdown(f"- `{cid}`")
                        else:
                            st.markdown("_(none)_")

                    st.divider()
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Confidence", f"{answer.get('confidence', 0):.2f}")
                    m2.metric("Tokens used", data.get("tokens_used", "—"))
                    m3.metric("Latency (ms)", data.get("latency_ms", "—"))
                    m4.metric("Cost (USD)", f"${data.get('cost_usd', 0):.6f}")

                    with st.expander("Full JSON response"):
                        st.json(data)

with tab_debug:
    st.subheader("GET /debug/retrieve")
    st.caption("No LLM call. Embeds the question, queries Pinecone, shows raw similarity scores.")

    debug_question = st.text_input(
        "Question", placeholder="Check what would be retrieved for this question...", key="debug_q"
    )
    top_k = st.number_input("top_k", min_value=1, max_value=20, value=5)

    if st.button("Retrieve", type="primary"):
        if not debug_question.strip():
            st.error("Question is required.")
        else:
            try:
                response = httpx.get(
                    f"{base_url}/debug/retrieve",
                    params={"q": debug_question, "top_k": top_k},
                    timeout=30.0,
                )
            except httpx.HTTPError as exc:
                st.error(f"Request failed: {exc}")
            else:
                if response.status_code != 200:
                    st.error(f"HTTP {response.status_code}")
                    st.json(response.json())
                else:
                    data = response.json()
                    st.caption(f"Relevance threshold: {data['threshold']}")

                    for chunk in data["chunks"]:
                        passes = chunk["passes_threshold"]
                        icon = "✅" if passes else "❌"
                        label = f"{icon} score={chunk['score']:.4f} — {chunk['document_id']} (chunk {chunk['chunk_index']})"
                        with st.expander(label, expanded=passes):
                            if chunk.get("source"):
                                st.caption(f"source: {chunk['source']}")
                            st.write(chunk["text"])

                    with st.expander("Full JSON response"):
                        st.json(data)
