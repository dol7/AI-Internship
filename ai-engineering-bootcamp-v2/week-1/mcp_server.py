"""Standalone MCP server exposing the on-call knowledge-base search as an
MCP tool over stdio.

Wraps rag_core.py's search_runbooks() -- the exact same RAG lookup that
/ask and the plain-FunctionTool agent already use -- so this is a second
transport for reaching the same capability, not a second implementation of
it. Imports rag_core directly (not main) so this subprocess only pays for
OpenAI/Pinecone/langchain, not FastAPI and both ADK Agents too. Run
directly (`python mcp_server.py`) it speaks MCP over stdin/stdout; main.py
launches it as a subprocess via ADK's StdioConnectionParams for the
/agent/mcp endpoint.
"""

from mcp.server.fastmcp import FastMCP

from rag_core import search_runbooks as _search_runbooks

mcp = FastMCP("oncall-runbooks")


@mcp.tool()
def search_runbooks(question: str) -> dict:
    """Search the on-call runbook/postmortem knowledge base for information
    relevant to this incident question."""
    return _search_runbooks(question)


if __name__ == "__main__":
    mcp.run(transport="stdio")
