"""Mock accounts from configuration. Sessions live in the Event Store."""

from __future__ import annotations

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
