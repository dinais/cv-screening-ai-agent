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
    credentials = [
        Credential(
            email=config.HR_EMAIL,
            password_hash=generate_password_hash(config.HR_PASSWORD),
            role=ROLE_HR,
        )
    ]
    for email, password in _candidate_accounts(config):
        credentials.append(
            Credential(
                email=email,
                password_hash=generate_password_hash(password),
                role=ROLE_CANDIDATE,
            )
        )
    return IdentityDirectory(credentials)


def _candidate_accounts(config) -> list[tuple[str, str]]:
    accounts = [(config.CANDIDATE_EMAIL, config.CANDIDATE_PASSWORD)]
    extra = str(getattr(config, "EXTRA_CANDIDATES", "") or "")
    for item in extra.split(","):
        item = item.strip()
        if ":" not in item:
            continue
        email, password = item.split(":", 1)
        email = email.strip()
        if email and password:
            accounts.append((email, password))
    return accounts
