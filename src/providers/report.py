"""The evaluation report every LLMProvider must return (features.md, Feature 5)."""

from __future__ import annotations

import json
import logging
import re

from src.cv_pdf import readable_cv_text

logger = logging.getLogger(__name__)

STATUSES = ("recommended", "not_recommended")
SKILL_MATCHES = ("met", "partial", "missing")
TEXT_FIELDS = ("strengths", "weaknesses", "missing_information", "recommendation")
_STATUS_ALIASES = {
    "recommend": "recommended",
    "yes": "recommended",
    "fit": "recommended",
    "suitable": "recommended",
    "strong_fit": "recommended",
    "good_fit": "recommended",
    "no": "not_recommended",
    "unfit": "not_recommended",
    "unsuitable": "not_recommended",
    "reject": "not_recommended",
    "rejected": "not_recommended",
    "poor_fit": "not_recommended",
}
_MATCH_ALIASES = {
    "yes": "met",
    "full": "met",
    "strong": "met",
    "meets": "met",
    "matched": "met",
    "present": "met",
    "partially": "partial",
    "partially_met": "partial",
    "some": "partial",
    "weak": "partial",
    "no": "missing",
    "none": "missing",
    "unmet": "missing",
    "not_met": "missing",
    "absent": "missing",
}

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
    """Find the report object in model output, even when prose surrounds it.

    A Deep Agent transcript can contain several JSON objects. An earlier draft
    must not hide a later object that has the required fields.
    """
    decoder = json.JSONDecoder()
    found: list[dict] = []
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found.append(value)
    if not found:
        raise ReportError("The model did not return JSON.")
    best = found[0]
    best_rank = (_report_quality(best), 0)
    for index, value in enumerate(found[1:], start=1):
        rank = (_report_quality(value), index)
        if rank >= best_rank:
            best = value
            best_rank = rank
    return best


_PLACEHOLDERS = {"none", "n/a", "na", "null", "nil", "n.a", "nothing", "-", "—"}


def require_report(report: object, cv_text: str = "") -> dict:
    """Normalise a report, or raise ReportError when it cannot be recorded."""
    if not isinstance(report, dict):
        raise ReportError("The model report was empty.")
    repaired = repair_report(report, cv_text)
    if repaired["status"] not in STATUSES or not all(repaired[field] for field in TEXT_FIELDS):
        missing = [name for name in ("status", *TEXT_FIELDS) if not repaired.get(name)]
        raise ReportError("The model report was incomplete: " + ", ".join(missing) + ".")
    if not repaired["skill_breakdown"]:
        raise ReportError("The model report has no skill breakdown.")
    return repaired


def repair_report(report: dict, cv_text: str = "") -> dict:
    """Fill a missing score and placeholder narrative from the skill breakdown.

    A skill the model marked missing or partial is marked met when the CV names it. The embedding score is not involved.
    A stored event is not rewritten. The query uses this so an old report still shows every field.
    """
    status = _normalise_status(report.get("status"))
    breakdown = _skill_breakdown(report.get("skill_breakdown"))
    breakdown, corrected = _align_breakdown(breakdown, cv_text)
    fields = {
        field: "" if _is_placeholder(report.get(field)) else str(report.get(field) or "").strip()
        for field in TEXT_FIELDS
    }
    if corrected and breakdown:
        fields = _complete_fields({field: "" for field in TEXT_FIELDS}, breakdown)
        score = _score_from_breakdown(breakdown)
        status = "recommended" if score >= 60 else "not_recommended"
        return {"status": status, "score": score, "skill_breakdown": breakdown, **fields}
    if status in STATUSES and breakdown:
        fields = _complete_fields(fields, breakdown)
    score = _score_value(report.get("score"))
    if _score_should_follow_breakdown(score, breakdown):
        score = _score_from_breakdown(breakdown)
        logger.warning("The model score was missing or zero. The report will use %s from the skill breakdown.", score)
    elif score is None:
        score = 0
        logger.warning("The model score was missing or invalid. The report will use 0.")
    return {"status": status, "score": score, "skill_breakdown": breakdown, **fields}


_SKILL_ALIASES = {
    "teamwork": ("team player", "team-player"),
    "problem-solving": ("problem solving",),
    "problem solving": ("problem-solving",),
    "node.js": ("nodejs", "node js"),
    "nodejs": ("node.js", "node js"),
    "express": ("express.js", "expressjs"),
    "express.js": ("express",),
}


def _align_breakdown(breakdown: list[dict], cv_text: str) -> tuple[list[dict], bool]:
    if not breakdown or not str(cv_text or "").strip():
        return breakdown, False
    text = readable_cv_text(cv_text)
    aligned: list[dict] = []
    corrected = False
    for item in breakdown:
        if item["match"] == "met":
            aligned.append(item)
            continue
        sentence = _cv_sentence(text, item["skill"])
        if not sentence:
            aligned.append(item)
            continue
        corrected = True
        aligned.append({"skill": item["skill"], "match": "met", "evidence": sentence})
    return aligned, corrected


def _cv_sentence(cv_text: str, skill: str) -> str:
    flat = " ".join(cv_text.split())
    if not flat:
        return ""
    for phrase in _skill_phrases(skill):
        if _has_phrase(flat, phrase):
            return _window(flat, phrase)
    alternatives = _split_skill(skill, r"\s+or\s+")
    if len(alternatives) > 1:
        for part in alternatives:
            sentence = _cv_sentence(flat, part)
            if sentence:
                return sentence
        return ""
    parts = _split_skill(skill, r"\s+and\s+")
    if len(parts) > 1:
        hits = [_cv_sentence(flat, part) for part in parts]
        if all(hits):
            return hits[0]
        return ""
    minimum = _years_requirement(skill)
    if minimum is None:
        return ""
    for match in re.finditer(r"(\d+)\s*\+?\s*years", flat, re.IGNORECASE):
        if int(match.group(1)) >= minimum:
            return _window(flat, match.group(0))
    return ""


def _split_skill(skill: str, pattern: str) -> list[str]:
    return [part.strip() for part in re.split(pattern, skill, flags=re.IGNORECASE) if part.strip()]


def _years_requirement(skill: str) -> int | None:
    match = re.fullmatch(
        r"(\d+)\s*\+\s*years(?:\s+of)?(?:\s+experience)?",
        skill.strip(),
        re.IGNORECASE,
    )
    if match is None:
        return None
    return int(match.group(1))


def _window(flat: str, phrase: str) -> str:
    match = re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", flat, re.IGNORECASE)
    if match is None:
        return flat[:240]
    start = flat.rfind(". ", 0, match.start())
    start = 0 if start < 0 else start + 2
    end = flat.find(". ", match.end())
    end = len(flat) if end < 0 else end + 1
    return " ".join(flat[start:end].split())[:240]


def _skill_phrases(skill: str) -> tuple[str, ...]:
    key = skill.strip().lower()
    return (key, *_SKILL_ALIASES.get(key, ()))


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.IGNORECASE) is not None


def _is_placeholder(value: object) -> bool:
    return str(value or "").strip().lower().rstrip(".") in _PLACEHOLDERS


def _score_should_follow_breakdown(score: int | None, breakdown: list[dict]) -> bool:
    if not breakdown:
        return False
    if score not in {None, 0}:
        return False
    return any(item["match"] in {"met", "partial"} for item in breakdown)


def _score_from_breakdown(breakdown: list[dict]) -> int:
    weights = {"met": 1.0, "partial": 0.5, "missing": 0.0}
    total = sum(weights.get(item["match"], 0.0) for item in breakdown)
    return max(0, min(100, round(100 * total / len(breakdown))))


def _complete_fields(fields: dict, breakdown: list[dict]) -> dict:
    """Fill a blank narrative from the skill breakdown. Does not replace text the model wrote."""
    filled = dict(fields)
    missing = [item["skill"] for item in breakdown if item["match"] == "missing"]
    partial = [item["skill"] for item in breakdown if item["match"] == "partial"]
    met = [item["skill"] for item in breakdown if item["match"] == "met"]
    gaps = missing + partial
    if not filled["weaknesses"]:
        filled["weaknesses"] = (
            "Not fully shown in the CV: " + ", ".join(gaps)
            if gaps
            else "No gap was identified from the CV against the required skills."
        )
    if not filled["missing_information"]:
        filled["missing_information"] = (
            "The CV does not show: " + ", ".join(missing)
            if missing
            else "No required skill was absent from the CV."
        )
    if not filled["strengths"]:
        filled["strengths"] = (
            "Shown in the CV: " + ", ".join(met) if met else "No required skill was fully shown in the CV."
        )
    if not filled["recommendation"]:
        filled["recommendation"] = (
            "The CV does not cover: " + ", ".join(gaps) if gaps else "The CV covers the required skills."
        )
    return filled


def _report_quality(value: dict) -> int:
    """How much of the required report is present. Used only to choose among JSON objects."""
    status_ok = _normalise_status(value.get("status")) in STATUSES
    fields_ok = all(str(value.get(field) or "").strip() for field in TEXT_FIELDS)
    breakdown_ok = bool(_skill_breakdown(value.get("skill_breakdown")))
    score_ok = _score_value(value.get("score")) is not None
    return int(status_ok) + int(fields_ok) + int(breakdown_ok) + int(score_ok) + int(status_ok and fields_ok and breakdown_ok)


def _normalise_status(value: object) -> str:
    status = str(value or "").strip().lower().rstrip(".").replace(" ", "_").replace("-", "_")
    if "not" in status and "recommend" in status:
        return "not_recommended"
    if "recommend" in status:
        return "recommended"
    return _STATUS_ALIASES.get(status, status)


def _normalise_match(value: object) -> str:
    match = str(value or "").strip().lower().rstrip(".").replace(" ", "_").replace("-", "_")
    if match in SKILL_MATCHES:
        return match
    if match in _MATCH_ALIASES:
        return _MATCH_ALIASES[match]
    if "partial" in match:
        return "partial"
    if match.startswith("not") or "missing" in match:
        return "missing"
    if "met" in match:
        return "met"
    return match


def _skill_breakdown(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    entries = []
    for item in value:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or "").strip()
        match = _normalise_match(item.get("match"))
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
