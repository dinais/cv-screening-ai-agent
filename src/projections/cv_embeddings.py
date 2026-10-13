"""Project ApplicationSubmitted events into Chroma. This module never appends events."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Callable

from src.persistence.event_store import EventStore, StoredEvent

logger = logging.getLogger(__name__)

COLLECTION_NAME = "cv_embeddings"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text"

EmbedFn = Callable[[str], list[float]]


class CvEmbeddingProjector:
    def __init__(
        self,
        events: EventStore,
        vector_path: str,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_EMBED_MODEL,
        embed: EmbedFn | None = None,
    ) -> None:
        self._events = events
        self._vector_path = vector_path
        self._base_url = (base_url or DEFAULT_OLLAMA_URL).rstrip("/")
        self._model = model or DEFAULT_EMBED_MODEL
        self._embed = embed
        self._client = None

    def project_application(self, application_id: str) -> bool:
        """Read one application event and upsert its vector. Never writes to the Event Store."""
        if not application_id:
            return False
        event = _application_event(self._events.load(application_id))
        if event is None:
            return False
        return self._upsert(event)

    def project_missing(self) -> int:
        """Embed application events that are not yet in Chroma. Never appends events."""
        stored = set(self._collection().get(include=[])["ids"])
        added = 0
        for event in self._events.load_by_types(("ApplicationSubmitted",)):
            application_id = _application_id(event)
            if not application_id or application_id in stored:
                continue
            if self._upsert(event):
                stored.add(application_id)
                added += 1
        return added

    def get(self, application_id: str) -> dict | None:
        found = self._collection().get(
            ids=[application_id],
            include=["documents", "metadatas", "embeddings"],
        )
        if not found["ids"]:
            return None
        embedding = found.get("embeddings")
        vector = None
        if embedding is not None and len(embedding) > 0 and embedding[0] is not None:
            vector = [float(value) for value in embedding[0]]
        return {
            "document": found["documents"][0],
            "metadata": found["metadatas"][0],
            "embedding": vector,
        }

    def _upsert(self, event: StoredEvent) -> bool:
        application_id = _application_id(event)
        cv_text = str(event.payload.get("cv_text") or "")
        if not application_id or not cv_text.strip():
            return False
        try:
            vector = self._embed_text(cv_text)
            if not vector:
                return False
            self._collection().upsert(
                ids=[application_id],
                embeddings=[vector],
                documents=[cv_text],
                metadatas=[
                    {
                        "job_id": str(event.payload.get("job_id") or ""),
                        "email": str(event.payload.get("email") or ""),
                        "full_name": str(event.payload.get("full_name") or ""),
                    }
                ],
            )
            return True
        except Exception:
            logger.exception("CV embedding failed for %s", application_id)
            return False

    def _embed_text(self, cv_text: str) -> list[float] | None:
        if self._embed is not None:
            return self._embed(cv_text)
        request = urllib.request.Request(
            f"{self._base_url}/api/embed",
            data=json.dumps({"model": self._model, "input": cv_text}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read().decode("utf-8"))
        embeddings = payload.get("embeddings")
        if embeddings:
            return [float(value) for value in embeddings[0]]
        embedding = payload.get("embedding")
        if embedding:
            return [float(value) for value in embedding]
        return None

    def _collection(self):
        if self._client is None:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=self._vector_path,
                settings=Settings(anonymized_telemetry=False),
            )
        return self._client.get_or_create_collection(name=COLLECTION_NAME)


def _application_event(events: list[StoredEvent]) -> StoredEvent | None:
    for event in events:
        if event.event_type == "ApplicationSubmitted":
            return event
    return None


def _application_id(event: StoredEvent) -> str:
    return str(event.payload.get("application_id") or event.aggregate_id)
