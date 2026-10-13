import logging

import pytest

from src import create_app
from src.commands.auth_commands import LoginCommand, LogoutCommand
from src.identity import IdentityDirectory
from src.persistence.event_store import (
    EventStore,
    InvalidEventError,
    _to_odbc_connection_string,
)
from src.queries.auth_queries import CurrentSessionQuery
from tests.test_auth import TestConfig


def test_login_appends_user_logged_in_and_logout_closes_the_session():
    app = create_app(TestConfig)
    client = app.test_client()
    response = client.post(
        "/login",
        data={"email": "hr@example.com", "password": "hr-pass"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Hiring dashboard" in response.data

    with client.session_transaction() as sess:
        ticket_id = sess["ticket_id"]

    store = app.extensions["event_store"]
    logged_in = store.load(ticket_id)
    assert [event.event_type for event in logged_in] == ["UserLoggedIn"]
    assert logged_in[0].payload == {"email": "hr@example.com", "role": "hr"}
    assert "password" not in logged_in[0].payload
    assert CurrentSessionQuery(store).execute(ticket_id).role == "hr"

    before = store.load(ticket_id)
    assert CurrentSessionQuery(store).execute(ticket_id).email == "hr@example.com"
    assert store.load(ticket_id) == before

    response = client.post("/logout", follow_redirects=True)
    assert response.status_code == 200
    logged_out = store.load(ticket_id)
    assert [event.event_type for event in logged_out] == ["UserLoggedIn", "UserLoggedOut"]
    assert [event.version for event in logged_out] == [1, 2]
    assert CurrentSessionQuery(store).execute(ticket_id) is None


def test_events_survive_a_new_connection(tmp_path):
    url = "sqlite:///" + (tmp_path / "events.sqlite").as_posix()
    first = EventStore(url)
    try:
        first.ensure_schema()
        first.ensure_schema()
        first.append(
            aggregate_id="ticket-1",
            aggregate_type="Session",
            event_type="UserLoggedIn",
            payload={"email": "hr@example.com", "role": "hr"},
        )
    finally:
        first.close()

    second = EventStore(url)
    try:
        events = second.load("ticket-1")
        assert len(events) == 1
        assert events[0].event_type == "UserLoggedIn"
        assert events[0].payload["email"] == "hr@example.com"
    finally:
        second.close()


def test_missing_fields_are_rejected_before_the_database_is_used():
    store = EventStore("sqlite:///:memory:")

    def explode():
        raise AssertionError("database was contacted")

    store._connect = explode
    with pytest.raises(InvalidEventError):
        store.append(
            aggregate_id="",
            aggregate_type="",
            event_type="",
            payload=None,
        )


def test_login_command_does_not_append_when_credentials_are_blank():
    class Spy:
        def append(self, **kwargs):
            raise AssertionError("database was contacted")

    result = LoginCommand(IdentityDirectory([]), Spy()).execute("", "")
    assert result.success is False
    assert result.ticket_id is None


def test_logout_command_rejects_a_missing_ticket_before_the_database():
    class Spy:
        def append(self, **kwargs):
            raise AssertionError("database was contacted")

    result = LogoutCommand(Spy()).execute(None)
    assert result.success is False


def test_somee_connection_string_is_converted_for_odbc():
    odbc = _to_odbc_connection_string(
        "data source=host.example;initial catalog=Screening;user id=login;pwd=secret;TrustServerCertificate=True",
        "ODBC Driver 17 for SQL Server",
    )
    assert odbc.startswith("DRIVER={ODBC Driver 17 for SQL Server};")
    assert "SERVER=host.example" in odbc
    assert "DATABASE=Screening" in odbc
    assert "UID=login" in odbc
    assert "PWD=secret" in odbc
    assert "TrustServerCertificate=yes" in odbc


def test_blank_database_url_uses_local_sqlite(caplog):
    with caplog.at_level(logging.WARNING):
        store = EventStore("")
    assert store.local_fallback is True
    assert store.sqlite_path.endswith("event_store.sqlite")
    assert "Somee" in caplog.text
    store.close()
