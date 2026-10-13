from __future__ import annotations

from src.commands.base import CommandHandler, CommandResult
from src.persistence.event_store import EventStore, InvalidEventError, StoredEvent

_STATUSES = {"recommended", "not_recommended"}


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
        strengths: str,
        weaknesses: str,
        missing_information: str,
        recommendation: str,
        semantic_match: float,
        sources: list[str],
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
        if (
            not application_id
            or not job_id
            or not email
            or status not in _STATUSES
            or clean_score is None
            or clean_match is None
            or clean_sources is None
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
                    "strengths": strengths,
                    "weaknesses": weaknesses,
                    "missing_information": missing_information,
                    "recommendation": recommendation,
                    "semantic_match": clean_match,
                    "sources": clean_sources,
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


def _sources(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        cleaned.append(item.strip())
    return cleaned
