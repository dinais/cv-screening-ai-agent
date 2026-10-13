from __future__ import annotations

import secrets

from src.commands.base import CommandHandler, CommandResult
from src.identity import IdentityDirectory
from src.persistence.event_store import EventStore, InvalidEventError


class LoginCommand(CommandHandler):
    def __init__(self, directory: IdentityDirectory, events: EventStore) -> None:
        self._directory = directory
        self._events = events

    def execute(self, email: str, password: str) -> CommandResult:
        credential = self._directory.authenticate(email, password)
        if credential is None:
            return CommandResult.fail("Invalid email or password.")
        ticket_id = secrets.token_urlsafe(32)
        try:
            self._events.append(
                aggregate_id=ticket_id,
                aggregate_type="Session",
                event_type="UserLoggedIn",
                payload={"email": credential.email, "role": credential.role},
            )
        except InvalidEventError as exc:
            return CommandResult.fail(str(exc))
        return CommandResult.ok(ticket_id=ticket_id)


class LogoutCommand(CommandHandler):
    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(self, ticket_id: str | None) -> CommandResult:
        if not (ticket_id or "").strip():
            return CommandResult.fail("Missing session.")
        try:
            self._events.append(
                aggregate_id=ticket_id,
                aggregate_type="Session",
                event_type="UserLoggedOut",
                payload={},
            )
        except InvalidEventError as exc:
            return CommandResult.fail(str(exc))
        return CommandResult.ok()
