from __future__ import annotations

import uuid

from src.commands.base import CommandHandler, CommandResult
from src.persistence.event_store import EventStore, InvalidEventError


class CreateJobCommand(CommandHandler):
    """Append a JobCreated event. The command does not read the job back."""

    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(self, *, title: str, requirements: str, created_by: str) -> CommandResult:
        title = (title or "").strip()
        requirements = (requirements or "").strip()
        created_by = (created_by or "").strip()
        if not title or not requirements or not created_by:
            return CommandResult.fail("A job needs a title, requirements, and creator.")

        job_id = str(uuid.uuid4())
        try:
            self._events.append(
                aggregate_id=job_id,
                aggregate_type="Job",
                event_type="JobCreated",
                payload={
                    "job_id": job_id,
                    "title": title,
                    "requirements": requirements,
                    "created_by": created_by,
                },
            )
        except InvalidEventError as exc:
            return CommandResult.fail(str(exc))
        return CommandResult.ok(reference_id=job_id)
