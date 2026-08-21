"""Standalone MCP server exposing the on-call knowledge-base search as an
MCP tool over stdio.

Wraps main.py's existing search_runbooks() -- the exact same in-process RAG
lookup that /ask and the plain-FunctionTool agent already use -- so this is
a second transport for reaching the same capability, not a second
implementation of it. Run directly (`python mcp_server.py`) it speaks MCP
over stdin/stdout; main.py launches it as a subprocess via ADK's
StdioConnectionParams for the /agent/mcp endpoint.
"""

from mcp.server.fastmcp import FastMCP

from main import search_runbooks as _search_runbooks

mcp = FastMCP("oncall-runbooks")


@mcp.tool()
def search_runbooks(question: str) -> dict:
    """Search the on-call runbook/postmortem knowledge base for information
    relevant to this incident question."""
    return _search_runbooks(question)


if __name__ == "__main__":
    mcp.run(transport="stdio")
