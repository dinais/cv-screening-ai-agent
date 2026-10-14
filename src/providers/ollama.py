"""Local Ollama in Docker. Embeddings use nomic-embed-text, evaluation a Deep Agent on llama3.2."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Callable

from src.providers.base import LLMError, LLMProvider
from src.providers.report import REPORT_SCHEMA, SYSTEM_PROMPT, parse_model_text, require_report

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_CHAT_MODEL = "llama3.2"


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        embed_model: str = DEFAULT_EMBED_MODEL,
        chat_model: str = DEFAULT_CHAT_MODEL,
        deep_agent_factory: Callable | None = None,
    ) -> None:
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._embed_model = embed_model or DEFAULT_EMBED_MODEL
        self._chat_model = chat_model or DEFAULT_CHAT_MODEL
        self._deep_agent_factory = deep_agent_factory or production_deep_agent

    def embed(self, text: str) -> list[float]:
        payload = self._post("/api/embed", {"model": self._embed_model, "input": text}, timeout=120)
        embeddings = payload.get("embeddings")
        if embeddings:
            return [float(value) for value in embeddings[0]]
        embedding = payload.get("embedding")
        if embedding:
            return [float(value) for value in embedding]
        raise LLMError("Local Ollama returned no embedding.")

    def evaluate(self, evidence: dict) -> dict:
        try:
            agent = self._deep_agent_factory(self._base_url, self._chat_model, SYSTEM_PROMPT)
            result = agent.invoke({"messages": [{"role": "user", "content": json.dumps(evidence)}]})
            return require_report(parse_model_text(_message_text(result)))
        except Exception:
            logger.warning(
                "Deep Agent did not return a valid report. Asking local Ollama model %s with the report schema.",
                self._chat_model,
            )
        payload = self._post(
            "/api/chat",
            {
                "model": self._chat_model,
                "stream": False,
                "format": REPORT_SCHEMA,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(evidence)},
                ],
            },
            timeout=300,
        )
        content = str((payload.get("message") or {}).get("content") or "")
        return require_report(parse_model_text(content))

    def _post(self, path: str, body: dict, timeout: int) -> dict:
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"Local Ollama at {self._base_url} did not answer {path}.") from exc


def production_deep_agent(base_url: str, model: str, system_prompt: str):
    from deepagents import (
        GeneralPurposeSubagentProfile,
        HarnessProfile,
        create_deep_agent,
        register_harness_profile,
    )
    from deepagents._models import get_model_identifier, get_model_provider
    from langchain_ollama import ChatOllama

    chat = ChatOllama(model=model, base_url=base_url, format="json", temperature=0)
    profile = HarnessProfile(
        excluded_tools=frozenset(
            {"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute", "task"}
        ),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        system_prompt_suffix="Return one JSON object and no other text.",
    )
    provider = get_model_provider(chat)
    identifier = get_model_identifier(chat)
    keys = [f"{provider}:{identifier}"] if provider and identifier else []
    if identifier:
        keys.append(str(identifier))
    for key in keys:
        register_harness_profile(key, profile)
    return create_deep_agent(model=chat, system_prompt=system_prompt)


def _message_text(result: dict) -> str:
    structured = result.get("structured_response")
    if hasattr(structured, "model_dump"):
        return json.dumps(structured.model_dump())
    if isinstance(structured, dict):
        return json.dumps(structured)
    messages = result.get("messages") or []
    chunks = [_content_text(getattr(message, "content", message)) for message in messages]
    text = "\n".join(chunk for chunk in chunks if chunk.strip())
    if not text.strip():
        raise LLMError("The model returned nothing.")
    return text


def _content_text(content: object) -> str:
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or ""))
            else:
                parts.append(str(getattr(part, "text", part) or ""))
        return "".join(parts)
    return str(content or "")
