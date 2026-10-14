"""Tavily Search API client. Only the screening-mcp server imports this module."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_RESULTS = 10


class TavilyError(RuntimeError):
    """Tavily search failed. The MCP tool reports it as an error result."""


def tavily_search(api_key: str, query: str, max_results: int = 5, urlopen=urllib.request.urlopen) -> list[dict]:
    api_key = (api_key or "").strip()
    query = (query or "").strip()
    if not api_key:
        raise TavilyError("TAVILY_API_KEY is missing.")
    if not query:
        raise TavilyError("The search query is empty.")
    if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= MAX_RESULTS:
        raise TavilyError(f"max_results must be an integer from 1 to {MAX_RESULTS}.")

    request = urllib.request.Request(
        TAVILY_SEARCH_URL,
        data=json.dumps({"query": query, "max_results": max_results}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise TavilyError(f"Tavily returned HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise TavilyError("Tavily could not be reached.") from exc

    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise TavilyError("Tavily returned no results list.")
    hits = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if url:
            hits.append(
                {
                    "title": str(row.get("title") or "").strip(),
                    "url": url,
                    "content": str(row.get("content") or "").strip(),
                }
            )
    return hits
