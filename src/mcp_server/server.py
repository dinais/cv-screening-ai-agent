"""screening-mcp: the project MCP server (features.md, Feature 6).

Both tools are read-only. No tool appends events or upserts vectors.
A raised exception becomes an MCP error result, never an empty success.
"""

from __future__ import annotations

from src.config import Config
from src.mcp_server.tavily import TavilyError, tavily_search
from src.providers import provider_from_config
from src.queries.cv_match import CvMatchQuery, RagError

SERVER_NAME = "screening-mcp"


def web_search_tool(query: str, max_results: int = 5, config=Config) -> dict:
    """Search the web through Tavily. Returns {"results": [{title, url, content}]}."""
    return {"results": tavily_search(config.TAVILY_API_KEY, query, max_results)}


def semantic_cv_match_tool(application_id: str, requirements: str, matcher: CvMatchQuery) -> dict:
    """Cosine similarity between one stored CV vector and the job requirements."""
    return {"application_id": application_id, "semantic_match": matcher.match(application_id, requirements)}


def build_server(config=Config):
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError

    matcher = CvMatchQuery(config.VECTOR_DB_PATH, provider_from_config(config))
    server = MCPServer(SERVER_NAME, log_level="WARNING")

    @server.tool()
    def web_search(query: str, max_results: int = 5) -> dict:
        """Search the web with Tavily. max_results is 1 to 10. Returns {"results": [{title, url, content}]}."""
        try:
            return web_search_tool(query, max_results, config)
        except TavilyError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool()
    def semantic_cv_match(application_id: str, requirements: str) -> dict:
        """Compare one candidate's stored CV vector with job requirements. Returns semantic_match from 0 to 1."""
        try:
            return semantic_cv_match_tool(application_id, requirements, matcher)
        except RagError as exc:
            raise ToolError(str(exc)) from exc

    return server
