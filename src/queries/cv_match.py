"""Read-only RAG against cv_embeddings.

The job requirements are embedded so Chroma can be queried. This module does not
upsert vectors and does not append events. CV embeddings stay in Feature 4.
"""

from __future__ import annotations

import math

from src.projections.cv_embeddings import COLLECTION_NAME, embedding_provider
from src.providers.base import LLMProvider


class RagError(RuntimeError):
    """The semantic match could not be read. Nothing is written."""


class CvMatchQuery:
    def __init__(self, vector_path: str, provider: LLMProvider) -> None:
        self._vector_path = vector_path
        self._provider = provider
        self._client = None

    def match(self, application_id: str, requirements: str) -> float:
        """Return cosine similarity between this CV vector and the job requirements."""
        application_id = (application_id or "").strip()
        requirements = (requirements or "").strip()
        if not application_id or not requirements:
            raise RagError("A semantic match needs an application and job requirements.")

        stored, made_by = self._stored_vector(application_id)
        if not stored:
            raise RagError(f"No CV vector for {application_id}.")
        if made_by != self._provider.name:
            raise RagError(
                f"The CV vector for {application_id} was made by {made_by}, not {self._provider.name}. "
                "Rebuild it with `python -m src.projections`."
            )
        try:
            query_vector = [float(value) for value in self._provider.embed(requirements)]
        except Exception as exc:
            raise RagError("The job requirements could not be embedded.") from exc
        if not query_vector or len(query_vector) != len(stored):
            raise RagError("The requirements embedding could not be compared with the CV vector.")

        self._query_collection(query_vector)
        return _cosine(query_vector, stored)

    def _stored_vector(self, application_id: str) -> tuple[list[float] | None, str]:
        found = self._collection().get(ids=[application_id], include=["embeddings", "metadatas"])
        ids = found.get("ids") or []
        if not ids:
            return None, ""
        embeddings = found.get("embeddings")
        if embeddings is None or len(embeddings) == 0 or embeddings[0] is None:
            return None, ""
        metadatas = found.get("metadatas") or [None]
        return [float(value) for value in list(embeddings[0])], embedding_provider(metadatas[0])

    def _query_collection(self, query_vector: list[float]) -> None:
        count = self._collection().count()
        if count < 1:
            raise RagError("The CV collection is empty.")
        try:
            self._collection().query(query_embeddings=[query_vector], n_results=min(10, count))
        except Exception as exc:
            raise RagError("The CV collection query failed.") from exc

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
    return round(max(-1.0, min(1.0, score)), 4)
