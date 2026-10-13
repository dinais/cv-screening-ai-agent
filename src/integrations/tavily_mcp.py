"""Tavily search through the Model Context Protocol.

This module starts the tavily-mcp server and calls its tavily_search tool.
It does not call the Tavily HTTP API.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from typing import Callable

ToolCall = Callable[[str, dict], object]


class McpError(RuntimeError):
    """The MCP search failed. The caller must not record an evaluation."""


@dataclass(frozen=True)
class McpServerSpec:
    command: str
    args: tuple[str, ...]
    api_key: str


class TavilyMcpSearch:
    def __init__(self, api_key: str, call_tool: ToolCall | None = None) -> None:
        self._api_key = (api_key or "").strip()
        self._call_tool = call_tool

    def server_spec(self) -> McpServerSpec:
        command = shutil.which("npx") or "npx"
        return McpServerSpec(command=command, args=("-y", "tavily-mcp"), api_key=self._api_key)

    def research(self, title: str, requirements: str, cv_text: str) -> list[dict]:
        """Search industry expectations and public facts named in the CV."""
        industry = self.search(
            f"Current industry expectations for {title}. Requirements: {requirements}"
        )
        public = self.search(
            "Public facts about the employers, projects, and skills named here: "
            + (cv_text or "")[:1000]
        )
        return _dedupe(industry + public)

    def search(self, query: str) -> list[dict]:
        query = (query or "").strip()
        if not self._api_key:
            raise McpError("TAVILY_API_KEY is missing.")
        if not query:
            raise McpError("The Tavily query is empty.")
        if self._call_tool is not None:
            raw = self._call_tool("tavily_search", {"query": query, "max_results": 5})
        else:
            raw = asyncio.run(self._call_mcp(query))
        return parse_tavily_results(raw)

    async def _call_mcp(self, query: str) -> object:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise McpError("The MCP client is not installed.") from exc

        spec = self.server_spec()
        env = os.environ.copy()
        env["TAVILY_API_KEY"] = spec.api_key
        params = StdioServerParameters(command=spec.command, args=list(spec.args), env=env)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "tavily_search",
                        {"query": query, "max_results": 5},
                    )
        except McpError:
            raise
        except Exception as exc:
            raise McpError("The Tavily MCP server failed.") from exc
        if getattr(result, "is_error", False) or getattr(result, "isError", False):
            message = _content_text(result).strip() or "The Tavily MCP tool returned an error."
            raise McpError(message[:500])
        structured = getattr(result, "structured_content", None)
        if structured is None:
            structured = getattr(result, "structuredContent", None)
        if isinstance(structured, (dict, list)):
            return structured
        text = _content_text(result)
        if not text.strip():
            raise McpError("The Tavily MCP tool returned no content.")
        return text


def _content_text(result: object) -> str:
    parts = []
    for block in getattr(result, "content", []) or []:
        text = _block_text(block)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _block_text(block: object) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        return str(block.get("text") or "")
    return str(getattr(block, "text", "") or "")


def parse_tavily_results(raw: object) -> list[dict]:
    """Read search hits from JSON, JSON wrapped in logs, or plain Title/URL text."""
    payload = _decode_payload(raw)
    if isinstance(payload, dict):
        error = payload.get("error")
        if error and "results" not in payload:
            raise McpError(str(error)[:500])
    rows = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise McpError("The Tavily MCP tool returned no results list.")
    hits = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        hits.append(
            {
                "title": str(row.get("title") or "").strip(),
                "url": url,
                "content": str(row.get("content") or "").strip(),
            }
        )
    return hits


def _decode_payload(raw: object) -> object:
    if isinstance(raw, (dict, list)):
        return raw
    text = _strip_noise(raw if isinstance(raw, str) else str(raw)).strip()
    if not text:
        raise McpError("The Tavily MCP tool returned empty content.")
    embedded = _embedded_json(text)
    if embedded is not None:
        return embedded
    plain = _plain_hits(text)
    if plain is not None:
        return plain
    raise McpError(f"The Tavily MCP tool returned: {text[:500]}")


def _strip_noise(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def _embedded_json(text: str) -> object | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, str) and value != text:
            nested = _embedded_json(value)
            if nested is not None:
                return nested
        return value
    return None


def _plain_hits(text: str) -> list[dict] | None:
    hits = []
    for chunk in re.split(r"\n(?=Title:)", text):
        url_match = re.search(r"^URL:\s*(\S+)", chunk, re.MULTILINE)
        if url_match is None:
            continue
        title_match = re.search(r"^Title:\s*(.*)$", chunk, re.MULTILINE)
        content_match = re.search(r"^Content:\s*(.*)$", chunk, re.MULTILINE | re.DOTALL)
        hits.append(
            {
                "title": title_match.group(1).strip() if title_match else "",
                "url": url_match.group(1).strip(),
                "content": content_match.group(1).strip() if content_match else "",
            }
        )
    return hits or None


def _dedupe(hits: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for hit in hits:
        if hit["url"] in seen:
            continue
        seen.add(hit["url"])
        unique.append(hit)
    return unique
