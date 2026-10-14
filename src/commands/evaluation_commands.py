from __future__ import annotations

from src.commands.base import CommandHandler, CommandResult
from src.persistence.event_store import EventStore, InvalidEventError, StoredEvent
from src.providers import PROVIDERS

_STATUSES = {"recommended", "not_recommended"}
_SKILL_MATCHES = {"met", "partial", "missing"}


class EvaluateCandidateCommand(CommandHandler):
    """Append one CandidateEvaluated event. The command does not return the assessment."""

    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(
        self,
        *,
        application_id: str,
        job_id: str,
        email: str,
        status: str,
        score: int,
        skill_breakdown: list[dict],
        strengths: str,
        weaknesses: str,
        missing_information: str,
        recommendation: str,
        semantic_match: float,
        sources: list[str],
        provider: str,
    ) -> CommandResult:
        application_id = (application_id or "").strip()
        job_id = (job_id or "").strip()
        email = (email or "").strip()
        status = (status or "").strip().lower()
        strengths = (strengths or "").strip()
        weaknesses = (weaknesses or "").strip()
        missing_information = (missing_information or "").strip()
        recommendation = (recommendation or "").strip()
        clean_score = _score(score)
        clean_match = _semantic_match(semantic_match)
        clean_sources = _sources(sources)
        clean_breakdown = _skill_breakdown(skill_breakdown)
        provider = (provider or "").strip().lower()
        if (
            not application_id
            or not job_id
            or not email
            or status not in _STATUSES
            or clean_score is None
            or clean_match is None
            or clean_sources is None
            or not clean_breakdown
            or provider not in PROVIDERS
            or not strengths
            or not weaknesses
            or not missing_information
            or not recommendation
        ):
            return CommandResult.fail("An evaluation needs the application, a score, and a full report.")

        stream = self._events.load(application_id)
        submitted = _submitted(stream)
        if submitted is None:
            return CommandResult.fail("Unknown application.")
        if str(submitted.payload.get("job_id") or "") != job_id:
            return CommandResult.fail("The evaluation does not match this application.")
        if str(submitted.payload.get("email") or "").strip().lower() != email.lower():
            return CommandResult.fail("The evaluation does not match this application.")
        if any(event.event_type == "CandidateEvaluated" for event in stream):
            return CommandResult.fail("This application is already evaluated.")

        try:
            self._events.append(
                aggregate_id=application_id,
                aggregate_type="Application",
                event_type="CandidateEvaluated",
                payload={
                    "application_id": application_id,
                    "job_id": job_id,
                    "email": email,
                    "status": status,
                    "score": clean_score,
                    "skill_breakdown": clean_breakdown,
                    "strengths": strengths,
                    "weaknesses": weaknesses,
                    "missing_information": missing_information,
                    "recommendation": recommendation,
                    "semantic_match": clean_match,
                    "sources": clean_sources,
                    "provider": provider,
                },
            )
        except InvalidEventError as exc:
            return CommandResult.fail(str(exc))
        return CommandResult.ok(reference_id=application_id)


def _submitted(events: list[StoredEvent]) -> StoredEvent | None:
    for event in events:
        if event.event_type == "ApplicationSubmitted":
            return event
    return None


def _score(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if 0 <= value <= 100:
        return value
    return None


def _semantic_match(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    match = float(value)
    if match < -1 or match > 1:
        return None
    return round(match, 4)


def _skill_breakdown(value: object) -> list[dict] | None:
    if not isinstance(value, list) or not value:
        return None
    cleaned: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        skill = str(item.get("skill") or "").strip()
        match = str(item.get("match") or "").strip().lower()
        evidence = item.get("evidence", "")
        if not skill or match not in _SKILL_MATCHES or not isinstance(evidence, str):
            return None
        cleaned.append({"skill": skill, "match": match, "evidence": "" if match == "missing" else evidence.strip()})
    return cleaned


def _sources(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        cleaned.append(item.strip())
    return cleaned
