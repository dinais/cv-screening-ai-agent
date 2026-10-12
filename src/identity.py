"""In-memory identity until the Event Store is introduced in Feature 2."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from werkzeug.security import check_password_hash, generate_password_hash


ROLE_HR = "hr"
ROLE_CANDIDATE = "candidate"


@dataclass(frozen=True)
class Credential:
    email: str
    password_hash: str
    role: str


@dataclass(frozen=True)
class AuthTicket:
    ticket_id: str
    email: str
    role: str


class IdentityDirectory:
    def __init__(self, credentials: list[Credential]) -> None:
        self._by_email = {item.email.lower(): item for item in credentials}

    def authenticate(self, email: str, password: str) -> Credential | None:
        record = self._by_email.get((email or "").strip().lower())
        if record is None:
            return None
        if not check_password_hash(record.password_hash, password or ""):
            return None
        return record


class AuthTicketStore:
    """Write-side session tickets issued by login commands."""

    def __init__(self) -> None:
        self._tickets: dict[str, AuthTicket] = {}

    def issue(self, email: str, role: str) -> str:
        ticket_id = secrets.token_urlsafe(32)
        self._tickets[ticket_id] = AuthTicket(ticket_id=ticket_id, email=email, role=role)
        return ticket_id

    def get(self, ticket_id: str | None) -> AuthTicket | None:
        if not ticket_id:
            return None
        return self._tickets.get(ticket_id)

    def revoke(self, ticket_id: str | None) -> None:
        if ticket_id:
            self._tickets.pop(ticket_id, None)


def directory_from_config(config) -> IdentityDirectory:
    return IdentityDirectory(
        [
            Credential(
                email=config.HR_EMAIL,
                password_hash=generate_password_hash(config.HR_PASSWORD),
                role=ROLE_HR,
            ),
            Credential(
                email=config.CANDIDATE_EMAIL,
                password_hash=generate_password_hash(config.CANDIDATE_PASSWORD),
                role=ROLE_CANDIDATE,
            ),
        ]
    )
