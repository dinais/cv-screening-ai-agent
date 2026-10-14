"""Client for the screening-mcp server. The agent reaches Tavily and Chroma only through it.

One stdio session is opened per agent run. All MCP traffic stays inside a single
asyncio task on a background thread, because the MCP SDK's stdio transport must
be opened and closed by the same task.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import sys
import threading
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ToolCall = Callable[[str, dict], object]


class McpError(RuntimeError):
    """An MCP tool failed. The caller must not record an evaluation."""


class ScreeningMcpClient:
    def __init__(self, call_tool: ToolCall | None = None) -> None:
        self._call_tool = call_tool
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._queue: asyncio.Queue | None = None
        self._session_task: concurrent.futures.Future | None = None

    def __enter__(self) -> ScreeningMcpClient:
        if self._call_tool is None:
            self._start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def match(self, application_id: str, requirements: str) -> float:
        result = self.call("semantic_cv_match", {"application_id": application_id, "requirements": requirements})
        value = result.get("semantic_match") if isinstance(result, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise McpError("semantic_cv_match returned no score.")
        return float(value)

    def research(self, title: str, requirements: str, cv_text: str) -> list[dict]:
        """Search industry expectations and public facts named in the CV."""
        industry = self.web_search(f"Current industry expectations for {title}. Requirements: {requirements}")
        public = self.web_search(
            "Public facts about the employers, projects, and skills named here: " + (cv_text or "")[:1000]
        )
        return _dedupe(industry + public)

    def web_search(self, query: str, max_results: int = 5) -> list[dict]:
        result = self.call("web_search", {"query": query, "max_results": max_results})
        rows = result.get("results") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise McpError("web_search returned no results list.")
        return [row for row in rows if isinstance(row, dict) and row.get("url")]

    def call(self, name: str, arguments: dict) -> object:
        if self._call_tool is not None:
            return self._call_tool(name, arguments)
        if self._queue is None or self._loop is None:
            raise McpError("The screening-mcp session is not open.")
        reply: concurrent.futures.Future = concurrent.futures.Future()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, (name, arguments, reply))
        return _tool_payload(reply.result(timeout=600))

    def close(self) -> None:
        if self._loop is None:
            return
        if self._queue is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
        if self._session_task is not None:
            try:
                self._session_task.result(timeout=30)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=30)
        self._loop.close()
        self._loop = None
        self._queue = None

    def _start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="screening-mcp", daemon=True)
        self._thread.start()
        ready: concurrent.futures.Future = concurrent.futures.Future()
        self._session_task = asyncio.run_coroutine_threadsafe(self._serve(ready), self._loop)
        try:
            ready.result(timeout=120)
        except Exception as exc:
            self.close()
            raise McpError("The screening-mcp server did not start.") from exc

    async def _serve(self, ready: concurrent.futures.Future) -> None:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            ready.set_exception(McpError("The MCP client is not installed."))
            raise exc

        self._queue = asyncio.Queue()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp_server"],
            env=os.environ.copy(),
            cwd=str(PROJECT_ROOT),
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ready.set_result(None)
                    while True:
                        item = await self._queue.get()
                        if item is None:
                            return
                        name, arguments, reply = item
                        try:
                            reply.set_result(await session.call_tool(name, arguments))
                        except Exception as exc:
                            reply.set_exception(McpError(f"{name} failed: {exc}"))
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            raise


def _tool_payload(result: object) -> object:
    text = "\n".join(_block_text(block) for block in getattr(result, "content", []) or []).strip()
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        raise McpError(text[:500] or "The MCP tool returned an error.")
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        inner = structured.get("result")
        return inner if isinstance(inner, dict) and len(structured) == 1 else structured
    if not text:
        raise McpError("The MCP tool returned no content.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpError(f"The MCP tool returned: {text[:500]}") from exc


def _block_text(block: object) -> str:
    if isinstance(block, dict):
        return str(block.get("text") or "")
    return str(getattr(block, "text", "") or "")


def _dedupe(hits: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for hit in hits:
        if hit["url"] in seen:
            continue
        seen.add(hit["url"])
        unique.append(hit)
    return unique
