"""Minimal Streamlit UI for the live RAG + Agent service
(POST /ingest, POST /ask, GET /debug/retrieve, POST /agent).

Thin client only. All chunking, embedding, retrieval, generation, and the
ADK agent loop happen in the FastAPI service -- this page just calls its
endpoints over HTTP and displays the response. No OpenAI/Pinecone/Google
calls and no RAG/agent logic here.

Run:
  streamlit run rag_ui.py

Points at your API via the sidebar "API base URL" field, which defaults to
the API_BASE_URL environment variable if set (falls back to localhost).
No secrets live in this UI -- the API holds its own OpenAI/Pinecone/Google
keys server-side; this page only ever needs a URL.
"""

import os

import httpx
import streamlit as st

st.set_page_config(page_title="RAG + Agent Service UI", layout="wide")
st.title("Capstone Service — Ingest, Ask, Debug, Agent")
st.caption("Thin client only. All RAG and agent logic lives in the API, not here.")

default_base_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
base_url = st.sidebar.text_input("API base URL", value=default_base_url).rstrip("/")
st.sidebar.caption(
    "Defaults to the API_BASE_URL environment variable if set. "
    "No secrets are stored here -- the API holds its own keys server-side."
)

tab_ingest, tab_ask, tab_debug, tab_agent = st.tabs(["Ingest", "Ask", "Debug Retrieve", "Agent"])

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

def run_agent_and_render(endpoint_path: str, goal: str) -> None:
    """Wake the API, call the given agent endpoint with goal, and render its
    step log + final answer. Shared by both the plain-tool and MCP buttons
    below so the wake-up/render logic isn't duplicated per endpoint."""

    # Free-tier hosting means the API may be fully asleep (cold start
    # can take 60-90s+). One giant blocking call for that whole window
    # freezes this entire Streamlit app -- including its own connection
    # back to your browser -- and something in the chain (Render/
    # Cloudflare) can drop that connection before the wait is over,
    # surfacing as a browser-side "Failed to fetch" even though the
    # backend would have eventually succeeded. Splitting into several
    # short pings keeps the app visibly alive and responsive instead.
    status = st.empty()
    api_awake = False
    for attempt in range(1, 7):
        status.info(f"Waking up the API... (attempt {attempt}/6)")
        try:
            health = httpx.get(f"{base_url}/health", timeout=15.0)
            if health.status_code == 200:
                api_awake = True
                break
        except httpx.HTTPError:
            pass

    response = None
    if not api_awake:
        status.error("API did not wake up after ~90s. Wait a moment and click Run Agent again.")
    else:
        status.info("API is awake — running the agent (usually 10-30s, longer for MCP tool calls)...")
        try:
            # MCP path can chain two tool calls at up to 60s each on Render's
            # free-tier CPU -- give it real headroom instead of a tight bound.
            response = httpx.post(f"{base_url}{endpoint_path}", json={"goal": goal}, timeout=150.0)
        except httpx.HTTPError as exc:
            status.error(f"Request failed: {exc}")
            response = None
        else:
            status.empty()

    if response is not None:
        if response.status_code != 200:
            st.error(f"HTTP {response.status_code}")
            st.json(response.json())
        else:
            data = response.json()

            st.markdown("### Step log (Think → Act → Observe)")
            st.caption(
                "Live trail of the agent's run: 'Think' steps only appear if the "
                "model actually exposed reasoning content for that call -- some "
                "models go straight from Act to Observe with no separate Think part."
            )
            steps = data.get("steps", [])
            if not steps:
                st.info("No tool calls were made for this task.")
            for i, step in enumerate(steps, start=1):
                kind = step.get("kind")
                st.markdown(f"**Step {i}**")
                if kind == "think":
                    st.markdown("🧠 **Think:**")
                    st.code(step["content"], language="text")
                elif kind == "act":
                    st.markdown(f"🔧 **Act:** called `{step['tool']}` with {step['content']}")
                elif kind == "observe":
                    st.markdown(f"👀 **Observe** (from `{step['tool']}`):")
                    st.code(step["content"], language="text")
                else:
                    st.code(step, language="text")

            st.divider()
            st.markdown("### Final Answer")
            st.success(data["answer"])

            with st.expander("Full JSON response"):
                st.json(data)


with tab_agent:
    st.subheader("POST /agent  ·  POST /agent/mcp")
    st.caption(
        "The ADK on-call agent decides for itself how many times to call "
        "search_runbooks before answering -- this isn't a fixed pipeline. "
        "Same agent, same knowledge base, same tool -- the two buttons below "
        "differ only in how the tool is reached: a plain in-process Python "
        "function call, or a real MCP tool call (tools/list + tools/call "
        "JSON-RPC) against mcp_server.py running as a stdio subprocess."
    )

    goal = st.text_area(
        "Task / question for the agent",
        height=100,
        placeholder="e.g. Storefront search p99 latency spiked to 3s, no deploy correlates. What should I check?",
    )

    col_plain, col_mcp = st.columns(2)
    run_plain = col_plain.button("Run Agent (Function Tool)", type="primary", use_container_width=True)
    run_mcp = col_mcp.button("Run Agent (MCP Tool)", use_container_width=True)

    if run_plain or run_mcp:
        if not goal.strip():
            st.error("A task/question is required.")
        elif run_plain:
            st.caption("Tool call transport: plain in-process Python function (`/agent`)")
            run_agent_and_render("/agent", goal)
        else:
            st.caption("Tool call transport: MCP protocol over stdio (`/agent/mcp`)")
            run_agent_and_render("/agent/mcp", goal)

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
