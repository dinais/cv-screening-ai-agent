from __future__ import annotations

from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """The provider could not embed or evaluate. Callers must not record a result."""


class LLMProvider(ABC):
    """All model access. `name` is stored on vectors and on CandidateEvaluated events."""

    name: str = ""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return one vector for this text."""

    @abstractmethod
    def evaluate(self, evidence: dict) -> dict:
        """Return one evaluation report in the shape checked by `require_report`."""
