"""Project ApplicationSubmitted events into Chroma. This module never appends events."""

from __future__ import annotations

import logging

from src.persistence.event_store import EventStore, StoredEvent
from src.providers.base import LLMProvider

logger = logging.getLogger(__name__)

COLLECTION_NAME = "cv_embeddings"
LEGACY_PROVIDER = "ollama"


class CvEmbeddingProjector:
    def __init__(self, events: EventStore, vector_path: str, provider: LLMProvider) -> None:
        self._events = events
        self._vector_path = vector_path
        self._provider = provider
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
        """Embed applications with no vector, or with a vector from another provider. Never appends events."""
        stored = self._collection().get(include=["metadatas"])
        current = {
            application_id
            for application_id, metadata in zip(stored["ids"], stored["metadatas"] or [])
            if embedding_provider(metadata) == self._provider.name
        }
        added = 0
        for event in self._events.load_by_types(("ApplicationSubmitted",)):
            application_id = _application_id(event)
            if not application_id or application_id in current:
                continue
            if self._upsert(event):
                current.add(application_id)
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
            vector = self._provider.embed(cv_text)
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
                        "embedding_provider": self._provider.name,
                    }
                ],
            )
            return True
        except Exception:
            logger.exception("CV embedding failed for %s", application_id)
            return False

    def _collection(self):
        if self._client is None:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=self._vector_path,
                settings=Settings(anonymized_telemetry=False),
            )
        return self._client.get_or_create_collection(name=COLLECTION_NAME)


def embedding_provider(metadata: dict | None) -> str:
    """Vectors written before Feature 5 carry no provider. They came from Ollama."""
    return str((metadata or {}).get("embedding_provider") or LEGACY_PROVIDER)


def _application_event(events: list[StoredEvent]) -> StoredEvent | None:
    for event in events:
        if event.event_type == "ApplicationSubmitted":
            return event
    return None


def _application_id(event: StoredEvent) -> str:
    return str(event.payload.get("application_id") or event.aggregate_id)
