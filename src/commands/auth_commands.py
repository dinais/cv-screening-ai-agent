from __future__ import annotations

from src.commands.base import CommandHandler, CommandResult
from src.identity import AuthTicketStore, IdentityDirectory


class LoginCommand(CommandHandler):
    def __init__(self, directory: IdentityDirectory, tickets: AuthTicketStore) -> None:
        self._directory = directory
        self._tickets = tickets

    def execute(self, email: str, password: str) -> CommandResult:
        credential = self._directory.authenticate(email, password)
        if credential is None:
            return CommandResult.fail("Invalid email or password.")
        # Feature 2: append UserLoggedIn to the Event Store instead of a local ticket.
        ticket_id = self._tickets.issue(credential.email, credential.role)
        return CommandResult.ok(ticket_id=ticket_id)


class LogoutCommand(CommandHandler):
    def __init__(self, tickets: AuthTicketStore) -> None:
        self._tickets = tickets

    def execute(self, ticket_id: str | None) -> CommandResult:
        # Feature 2: append UserLoggedOut to the Event Store.
        self._tickets.revoke(ticket_id)
        return CommandResult.ok()
