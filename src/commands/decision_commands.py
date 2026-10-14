from __future__ import annotations

from src.commands.base import CommandHandler, CommandResult
from src.persistence.event_store import EventStore

_DECISIONS = {"accepted", "rejected"}


class DecideCandidateCommand(CommandHandler):
    """Append one CandidateDecided event. HR cannot decide the same application twice."""

    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(self, *, application_id: str, decision: str, decided_by: str) -> CommandResult:
        application_id = (application_id or "").strip()
        decision = (decision or "").strip().lower()
        decided_by = (decided_by or "").strip()
        if not application_id or decision not in _DECISIONS or not decided_by:
            return CommandResult.fail("A decision needs an application and must be accepted or rejected.")

        stream = self._events.load(application_id)
        submitted = next((event for event in stream if event.event_type == "ApplicationSubmitted"), None)
        if submitted is None:
            return CommandResult.fail("Unknown application.")
        if any(event.event_type == "CandidateDecided" for event in stream):
            return CommandResult.fail("This application already has a decision.")

        job_id = str(submitted.payload.get("job_id") or "")
        stored = self._events.append(
            aggregate_id=application_id,
            aggregate_type="Application",
            event_type="CandidateDecided",
            payload={
                "application_id": application_id,
                "job_id": job_id,
                "decision": decision,
                "decided_by": decided_by,
            },
        )
        return CommandResult.ok("Decision recorded.", reference_id=stored.aggregate_id)
