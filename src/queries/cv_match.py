"""Read-only RAG against cv_embeddings.

The job requirements are embedded so Chroma can be queried. This module does not
upsert vectors and does not append events. CV embeddings stay in Feature 4.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Callable

EmbedFn = Callable[[str], list[float]]
COLLECTION_NAME = "cv_embeddings"


class RagError(RuntimeError):
    """The semantic match could not be read. Nothing is written."""


class CvMatchQuery:
    def __init__(
        self,
        vector_path: str,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        embed: EmbedFn | None = None,
    ) -> None:
        self._vector_path = vector_path
        self._base_url = (base_url or "http://localhost:11434").rstrip("/")
        self._model = model or "nomic-embed-text"
        self._embed = embed
        self._client = None

    def match(self, application_id: str, requirements: str) -> float:
        """Return cosine similarity between this CV vector and the job requirements."""
        application_id = (application_id or "").strip()
        requirements = (requirements or "").strip()
        if not application_id or not requirements:
            raise RagError("A semantic match needs an application and job requirements.")

        stored = self._stored_vector(application_id)
        if not stored:
            raise RagError(f"No CV vector for {application_id}.")
        query_vector = self._embed_query(requirements)
        if not query_vector or len(query_vector) != len(stored):
            raise RagError("The requirements embedding could not be compared with the CV vector.")

        self._query_collection(query_vector)
        return _cosine(query_vector, stored)

    def _stored_vector(self, application_id: str) -> list[float] | None:
        found = self._collection().get(ids=[application_id], include=["embeddings"])
        ids = found.get("ids") or []
        if not ids:
            return None
        embeddings = found.get("embeddings")
        if embeddings is None or len(embeddings) == 0 or embeddings[0] is None:
            return None
        return [float(value) for value in list(embeddings[0])]

    def _query_collection(self, query_vector: list[float]) -> None:
        count = self._collection().count()
        if count < 1:
            raise RagError("The CV collection is empty.")
        try:
            self._collection().query(query_embeddings=[query_vector], n_results=min(10, count))
        except Exception as exc:
            raise RagError("The CV collection query failed.") from exc

    def _embed_query(self, requirements: str) -> list[float] | None:
        if self._embed is not None:
            return [float(value) for value in self._embed(requirements)]
        request = urllib.request.Request(
            f"{self._base_url}/api/embed",
            data=json.dumps({"model": self._model, "input": requirements}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RagError("Local Ollama did not embed the job requirements.") from exc
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


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        raise RagError("A zero vector cannot be matched.")
    score = dot / (left_norm * right_norm)
    if score < -1:
        score = -1.0
    elif score > 1:
        score = 1.0
    return round(score, 4)
