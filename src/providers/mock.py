"""Offline provider for machines without Ollama. Makes no network call."""

from __future__ import annotations

import hashlib
import math
import re

from src.providers.base import LLMError, LLMProvider

DIMENSIONS = 768
RECOMMEND_AT = 60

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.]*")
_SPLIT = re.compile(r"[,;\n/]|\band\b|\bor\b", re.IGNORECASE)
_STOPWORDS = frozenset(
    "a an the of in on at to for with from by as is are be have has years year experience "
    "knowledge strong good solid ability skills skill using use plus".split()
)
_MAX_SKILL_WORDS = 4
_MAX_SKILLS = 12


class MockLLMProvider(LLMProvider):
    name = "mock"

    def embed(self, text: str) -> list[float]:
        """Hash each word into one of 768 slots, so shared words raise cosine similarity."""
        tokens = _tokens(text)
        if not tokens:
            raise LLMError("There is no text to embed.")
        vector = [0.0] * DIMENSIONS
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % DIMENSIONS
            vector[slot] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]

    def evaluate(self, evidence: dict) -> dict:
        cv_text = str(evidence.get("cv_text") or "")
        cv_tokens = set(_tokens(cv_text))
        breakdown = [_judge_skill(skill, cv_tokens, cv_text) for skill in _skills(evidence.get("requirements"))]
        if not breakdown:
            raise LLMError("The job requirements name no skill to check.")

        coverage = sum({"met": 1.0, "partial": 0.5}.get(item["match"], 0.0) for item in breakdown) / len(breakdown)
        semantic = max(0.0, min(1.0, float(evidence.get("semantic_match") or 0.0)))
        score = round(100 * (0.6 * coverage + 0.4 * semantic))
        status = "recommended" if score >= RECOMMEND_AT else "not_recommended"

        met = [item["skill"] for item in breakdown if item["match"] == "met"]
        partial = [item["skill"] for item in breakdown if item["match"] == "partial"]
        missing = [item["skill"] for item in breakdown if item["match"] == "missing"]
        return {
            "status": status,
            "score": score,
            "skill_breakdown": breakdown,
            "strengths": f"The CV shows {_join(met)}." if met else "The CV does not clearly show any listed requirement.",
            "weaknesses": f"The CV does not show {_join(missing)}." if missing else "No listed requirement is absent from the CV.",
            "missing_information": (
                f"The CV only partly covers {_join(partial)}." if partial
                else "Depth and seniority cannot be judged by keyword matching. Read the CV directly."
            ),
            "recommendation": (
                "Mock evaluation. The CV covers most requirements. Proceed to HR review."
                if status == "recommended"
                else "Mock evaluation. The CV does not cover enough of the requirements."
            ),
        }


def _tokens(text: object) -> list[str]:
    return [token.rstrip(".") for token in _TOKEN.findall(str(text or "").lower())]


def _skills(requirements: object) -> list[str]:
    skills: list[str] = []
    for chunk in _SPLIT.split(str(requirements or "")):
        words = [word for word in _tokens(chunk) if word not in _STOPWORDS]
        if not words:
            continue
        names = [" ".join(words)] if len(words) <= _MAX_SKILL_WORDS else words
        for name in names:
            if name not in skills:
                skills.append(name)
    return skills[:_MAX_SKILLS]


def _judge_skill(skill: str, cv_tokens: set[str], cv_text: str) -> dict:
    words = skill.split()
    found = [word for word in words if word in cv_tokens]
    if len(found) == len(words):
        match = "met"
    elif found:
        match = "partial"
    else:
        return {"skill": skill, "match": "missing", "evidence": ""}
    return {"skill": skill, "match": match, "evidence": _evidence(cv_text, found[0])}


def _evidence(cv_text: str, word: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", cv_text):
        if word in _tokens(sentence):
            return sentence.strip()[:160]
    return ""


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
