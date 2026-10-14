"""Rebuild cv_embeddings from ApplicationSubmitted events: `python -m src.projections`.

Run it after changing LLM_PROVIDER. It reads events and upserts vectors only.
"""

from __future__ import annotations

import logging

from src.config import Config
from src.persistence.event_store import EventStore
from src.projections.cv_embeddings import CvEmbeddingProjector
from src.providers import provider_from_config


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    provider = provider_from_config(Config)
    projector = CvEmbeddingProjector(EventStore(Config.DATABASE_URL), Config.VECTOR_DB_PATH, provider)
    added = projector.project_missing()
    print(f"Embedded {added} CV(s) with the {provider.name} provider.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
