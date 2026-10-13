from __future__ import annotations

from src.identity import AuthTicket
from src.persistence.event_store import EventStore, StoredEvent
from src.queries.base import QueryHandler


def project_session(events: list[StoredEvent]) -> AuthTicket | None:
    """Rebuild the current session by replaying its events. Never writes."""
    email = ""
    role = ""
    active = False
    ticket_id = None
    for event in events:
        ticket_id = event.aggregate_id
        if event.event_type == "UserLoggedIn":
            email = str(event.payload.get("email") or "")
            role = str(event.payload.get("role") or "")
            active = bool(email and role)
        elif event.event_type == "UserLoggedOut":
            active = False
    if not active or not ticket_id or not email or not role:
        return None
    return AuthTicket(ticket_id=ticket_id, email=email, role=role)


class CurrentSessionQuery(QueryHandler):
    def __init__(self, events: EventStore) -> None:
        self._events = events

    def execute(self, ticket_id: str | None) -> AuthTicket | None:
        if not ticket_id:
            return None
        return project_session(self._events.load(ticket_id))
