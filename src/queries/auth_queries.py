from __future__ import annotations

from src.identity import AuthTicket, AuthTicketStore
from src.queries.base import QueryHandler


class CurrentSessionQuery(QueryHandler):
    def __init__(self, tickets: AuthTicketStore) -> None:
        self._tickets = tickets

    def execute(self, ticket_id: str | None) -> AuthTicket | None:
        return self._tickets.get(ticket_id)
