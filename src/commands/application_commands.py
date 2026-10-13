from __future__ import annotations

import uuid

from src.commands.base import CommandHandler, CommandResult
from src.persistence.event_store import EventStore, InvalidEventError, StoredEvent


class SubmitApplicationCommand(CommandHandler):
    """Append an ApplicationSubmitted event for an existing job."""

    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(
        self,
        *,
        job_id: str,
        full_name: str,
        email: str,
        cv_text: str,
    ) -> CommandResult:
        job_id = (job_id or "").strip()
        full_name = (full_name or "").strip()
        email = (email or "").strip()
        cv_text = cv_text or ""
        if not job_id or not full_name or not email:
            return CommandResult.fail("An application needs a job, a name, and an email.")

        if not _job_exists(self._events.load(job_id)):
            return CommandResult.fail("Unknown job.")

        if _already_applied(self._events.load_by_types(("ApplicationSubmitted",)), job_id, email):
            return CommandResult.fail("You have already applied to this job.")

        application_id = str(uuid.uuid4())
        try:
            self._events.append(
                aggregate_id=application_id,
                aggregate_type="Application",
                event_type="ApplicationSubmitted",
                payload={
                    "application_id": application_id,
                    "job_id": job_id,
                    "full_name": full_name,
                    "email": email,
                    "cv_text": cv_text,
                },
            )
        except InvalidEventError as exc:
            return CommandResult.fail(str(exc))
        return CommandResult.ok(reference_id=application_id)


def _job_exists(events: list[StoredEvent]) -> bool:
    return any(
        event.aggregate_type == "Job" and event.event_type == "JobCreated" for event in events
    )


def _already_applied(events: list[StoredEvent], job_id: str, email: str) -> bool:
    needle = email.strip().lower()
    for event in events:
        if event.event_type != "ApplicationSubmitted":
            continue
        if str(event.payload.get("job_id") or "") != job_id:
            continue
        if str(event.payload.get("email") or "").strip().lower() == needle:
            return True
    return False
