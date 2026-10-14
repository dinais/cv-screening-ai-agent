"""Start screening-mcp over stdio: `python -m src.mcp_server`. Stdout carries MCP messages only."""

from src.mcp_server.server import build_server

if __name__ == "__main__":
    build_server().run("stdio")
