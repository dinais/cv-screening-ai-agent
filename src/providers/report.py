"""The evaluation report every LLMProvider must return (features.md, Feature 5)."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

STATUSES = ("recommended", "not_recommended")
SKILL_MATCHES = ("met", "partial", "missing")
TEXT_FIELDS = ("strengths", "weaknesses", "missing_information", "recommendation")

SYSTEM_PROMPT = """
You judge whether one candidate fits one job.
Use only the CV text, the job requirements, the semantic match score, and the Tavily results in the user message.
Do not invent employers, skills, dates, or sources.
Return one JSON object and nothing else.
Keys:
- status: recommended or not_recommended
- score: integer from 0 to 100, the candidate match score
- skill_breakdown: a list with one entry per skill named in the job requirements.
  Each entry has skill (string), match (met, partial, or missing), and evidence
  (a short quote or paraphrase from the CV, empty when match is missing)
- strengths: string
- weaknesses: string
- missing_information: string
- recommendation: string
recommended means the CV fits the requirements. not_recommended means it does not.
You do not accept or reject the candidate. That decision belongs to HR.
""".strip()

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "score": {"type": "integer"},
        "skill_breakdown": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "match": {"type": "string", "enum": list(SKILL_MATCHES)},
                    "evidence": {"type": "string"},
                },
                "required": ["skill", "match", "evidence"],
            },
        },
        **{field: {"type": "string"} for field in TEXT_FIELDS},
    },
    "required": ["status", "score", "skill_breakdown", *TEXT_FIELDS],
}


class ReportError(RuntimeError):
    """The model report is missing or incomplete. No event is recorded."""


def parse_model_text(text: str) -> dict:
    """Find the report object in model output, even when prose surrounds it."""
    decoder = json.JSONDecoder()
    fallback = None
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if "status" in value and "score" in value:
            return value
        if fallback is None:
            fallback = value
    if fallback is not None:
        return fallback
    raise ReportError("The model did not return JSON.")


def require_report(report: object) -> dict:
    """Normalise a report, or raise ReportError when it cannot be recorded."""
    if not isinstance(report, dict):
        raise ReportError("The model report was empty.")
    status = str(report.get("status") or "").strip().lower().replace(" ", "_").replace("-", "_")
    score = _score_value(report.get("score"))
    if score is None:
        score = 0
        logger.warning("The model score was missing or invalid. The report will use 0.")
    fields = {field: str(report.get(field) or "").strip() for field in TEXT_FIELDS}
    breakdown = _skill_breakdown(report.get("skill_breakdown"))
    if status not in STATUSES or not all(fields.values()):
        raise ReportError("The model report was incomplete.")
    if not breakdown:
        raise ReportError("The model report has no skill breakdown.")
    return {"status": status, "score": score, "skill_breakdown": breakdown, **fields}


def _skill_breakdown(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    entries = []
    for item in value:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or "").strip()
        match = str(item.get("match") or "").strip().lower()
        if not skill or match not in SKILL_MATCHES:
            continue
        evidence = "" if match == "missing" else str(item.get("evidence") or "").strip()
        entries.append({"skill": skill, "match": match, "evidence": evidence})
    return entries


def _score_value(score: object) -> int | None:
    if isinstance(score, bool) or score is None:
        return None
    if isinstance(score, (int, float)):
        return _clamp_score(float(score))
    text = str(score).strip()
    if not text:
        return None
    try:
        return _clamp_score(float(text))
    except ValueError:
        pass
    match = re.search(r"\d+(?:\.\d+)?", text)
    if match is None:
        return None
    return _clamp_score(float(match.group(0)))


def _clamp_score(number: float) -> int:
    return max(0, min(100, int(round(number))))
