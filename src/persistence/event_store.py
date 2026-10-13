"""Append-only Event Store.

SQL is executed through a database driver. There is no ORM.
SQL Server (Somee) is used when DATABASE_URL is an ODBC connection string.
A blank DATABASE_URL stores events in a local SQLite file so the app can run
before the cloud database is configured.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SQLITE_PATH = PROJECT_ROOT / "data" / "event_store.sqlite"

_SQLITE_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS EventStore (
        EventId TEXT NOT NULL PRIMARY KEY,
        AggregateId TEXT NOT NULL,
        AggregateType TEXT NOT NULL,
        EventType TEXT NOT NULL,
        Payload TEXT NOT NULL,
        Version INTEGER NOT NULL,
        OccurredAt TEXT NOT NULL,
        UNIQUE (AggregateId, Version)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS IX_EventStore_AggregateId
    ON EventStore (AggregateId, Version)
    """,
)

_MSSQL_SCHEMA = (
    """
    IF OBJECT_ID(N'dbo.EventStore', N'U') IS NULL
    CREATE TABLE dbo.EventStore (
        EventId NVARCHAR(36) NOT NULL CONSTRAINT PK_EventStore PRIMARY KEY,
        AggregateId NVARCHAR(200) NOT NULL,
        AggregateType NVARCHAR(100) NOT NULL,
        EventType NVARCHAR(100) NOT NULL,
        Payload NVARCHAR(MAX) NOT NULL,
        Version INT NOT NULL,
        OccurredAt NVARCHAR(40) NOT NULL,
        CONSTRAINT UQ_EventStore_Aggregate_Version UNIQUE (AggregateId, Version)
    )
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.indexes
        WHERE name = N'IX_EventStore_AggregateId'
          AND object_id = OBJECT_ID(N'dbo.EventStore')
    )
    CREATE INDEX IX_EventStore_AggregateId ON dbo.EventStore (AggregateId, Version)
    """,
)


class InvalidEventError(ValueError):
    """An event is missing mandatory fields. The database is not contacted."""


@dataclass(frozen=True)
class StoredEvent:
    event_id: str
    aggregate_id: str
    aggregate_type: str
    event_type: str
    payload: dict
    version: int
    occurred_at: str


class EventStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = (database_url or "").strip()
        self._conn: sqlite3.Connection | None = None
        self.local_fallback = False
        self.sqlite_path = ""

        if not self._database_url:
            self._driver = "sqlite"
            self._sqlite_path = str(LOCAL_SQLITE_PATH)
            self.sqlite_path = self._sqlite_path
            self.local_fallback = True
            logger.warning(
                "DATABASE_URL is empty. Events are stored in local SQLite at %s. "
                "Set DATABASE_URL to the Somee SQL Server ODBC string before submission.",
                LOCAL_SQLITE_PATH,
            )
        elif self._database_url.startswith("sqlite:"):
            self._driver = "sqlite"
            self._sqlite_path = _sqlite_path(self._database_url)
            self.sqlite_path = self._sqlite_path
        else:
            self._driver = "mssql"
            self._sqlite_path = ""

    def ensure_schema(self) -> None:
        """Create the EventStore table when it is missing. Safe to call more than once."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            for statement in self._schema_statements():
                cursor.execute(statement)
            if self._driver == "mssql":
                conn.commit()
        except Exception:
            if self._driver == "mssql":
                conn.rollback()
            raise
        finally:
            self._release(conn)

    def append(
        self,
        *,
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        payload: dict,
    ) -> StoredEvent:
        payload_json = _validate_event(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            payload=payload,
        )
        self.ensure_schema()
        conn = self._connect()
        try:
            if self._driver == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute(self._max_version_sql(), (aggregate_id,))
            current = cursor.fetchone()[0]
            version = int(current or 0) + 1
            event_id = str(uuid.uuid4())
            occurred_at = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                self._insert_sql(),
                (
                    event_id,
                    aggregate_id,
                    aggregate_type,
                    event_type,
                    payload_json,
                    version,
                    occurred_at,
                ),
            )
            self._commit(conn)
        except Exception:
            self._rollback(conn)
            raise
        finally:
            self._release(conn)

        return StoredEvent(
            event_id=event_id,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            payload=json.loads(payload_json),
            version=version,
            occurred_at=occurred_at,
        )

    def load(self, aggregate_id: str) -> list[StoredEvent]:
        """Read one event stream in version order. This method never writes."""
        if not aggregate_id:
            return []
        return self._read(self._select_sql(), (aggregate_id,))

    def load_by_types(self, event_types: tuple[str, ...]) -> list[StoredEvent]:
        """Read matching events in occurrence order. This method never writes."""
        names = tuple(name for name in event_types if name)
        if not names:
            return []
        placeholders = ", ".join("?" for _ in names)
        return self._read(self._select_by_types_sql(placeholders), names)

    def _read(self, sql: str, params: tuple) -> list[StoredEvent]:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            if self._driver == "mssql":
                conn.commit()
            return [_row_to_event(row) for row in rows]
        finally:
            self._release(conn)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _schema_statements(self) -> tuple[str, ...]:
        if self._driver == "sqlite":
            return _SQLITE_SCHEMA
        return _MSSQL_SCHEMA

    def _max_version_sql(self) -> str:
        if self._driver == "sqlite":
            return "SELECT COALESCE(MAX(Version), 0) FROM EventStore WHERE AggregateId = ?"
        return (
            "SELECT COALESCE(MAX(Version), 0) "
            "FROM dbo.EventStore WITH (UPDLOCK, HOLDLOCK) "
            "WHERE AggregateId = ?"
        )

    def _insert_sql(self) -> str:
        return (
            f"INSERT INTO {self._table()} "
            "(EventId, AggregateId, AggregateType, EventType, Payload, Version, OccurredAt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )

    def _select_sql(self) -> str:
        return (
            "SELECT EventId, AggregateId, AggregateType, EventType, Payload, Version, OccurredAt "
            f"FROM {self._table()} WHERE AggregateId = ? ORDER BY Version ASC"
        )

    def _select_by_types_sql(self, placeholders: str) -> str:
        return (
            "SELECT EventId, AggregateId, AggregateType, EventType, Payload, Version, OccurredAt "
            f"FROM {self._table()} WHERE EventType IN ({placeholders}) "
            "ORDER BY OccurredAt ASC, Version ASC"
        )

    def _table(self) -> str:
        return "EventStore" if self._driver == "sqlite" else "dbo.EventStore"

    def _connect(self):
        if self._driver == "sqlite":
            if self._conn is None:
                if self._sqlite_path != ":memory:":
                    Path(self._sqlite_path).parent.mkdir(parents=True, exist_ok=True)
                self._conn = sqlite3.connect(self._sqlite_path, check_same_thread=False)
                self._conn.isolation_level = None
            return self._conn
        return _open_sql_server(self._database_url)

    def _release(self, conn) -> None:
        if self._driver != "sqlite" and conn is not None:
            conn.close()

    def _commit(self, conn) -> None:
        if self._driver == "sqlite":
            conn.execute("COMMIT")
        else:
            conn.commit()

    def _rollback(self, conn) -> None:
        if self._driver == "sqlite":
            conn.execute("ROLLBACK")
        else:
            conn.rollback()


def _validate_event(
    *,
    aggregate_id: str,
    aggregate_type: str,
    event_type: str,
    payload: dict,
) -> str:
    missing: list[str] = []
    if not str(aggregate_id or "").strip():
        missing.append("aggregate_id")
    elif len(str(aggregate_id)) > 200:
        missing.append("aggregate_id")
    if not str(aggregate_type or "").strip():
        missing.append("aggregate_type")
    elif len(str(aggregate_type)) > 100:
        missing.append("aggregate_type")
    if not str(event_type or "").strip():
        missing.append("event_type")
    elif len(str(event_type)) > 100:
        missing.append("event_type")
    if not isinstance(payload, dict):
        missing.append("payload")
    if missing:
        raise InvalidEventError(
            "Missing or invalid mandatory fields: " + ", ".join(missing)
        )
    try:
        return json.dumps(payload, separators=(",", ":"))
    except TypeError as exc:
        raise InvalidEventError("payload must be JSON-serializable") from exc


def _sqlite_path(database_url: str) -> str:
    if database_url in {"sqlite:///:memory:", "sqlite://"}:
        return ":memory:"
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(f"Unsupported SQLite URL: {database_url}")
    return database_url[len(prefix) :]


_ADO_TO_ODBC = {
    "data source": "SERVER",
    "server": "SERVER",
    "address": "SERVER",
    "addr": "SERVER",
    "network address": "SERVER",
    "initial catalog": "DATABASE",
    "database": "DATABASE",
    "user id": "UID",
    "uid": "UID",
    "pwd": "PWD",
    "password": "PWD",
    "trustservercertificate": "TrustServerCertificate",
    "packet size": "Packet Size",
    "workstation id": "WSID",
}

_SQL_SERVER_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server",
)


def _open_sql_server(database_url: str):
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError(
            "pyodbc is required to reach SQL Server. Install it with: pip install pyodbc"
        ) from exc
    odbc = _to_odbc_connection_string(database_url, _sql_server_driver(pyodbc))
    try:
        return pyodbc.connect(odbc, timeout=30)
    except Exception as exc:
        raise ConnectionError(
            "Could not connect to the Event Store. Check DATABASE_URL."
        ) from exc


def _sql_server_driver(pyodbc) -> str:
    installed = set(pyodbc.drivers())
    for name in _SQL_SERVER_DRIVERS:
        if name in installed:
            return name
    raise RuntimeError(
        "No SQL Server ODBC driver is installed. Install ODBC Driver 17 or 18 for SQL Server."
    )


def _to_odbc_connection_string(database_url: str, driver: str) -> str:
    """Accept an ODBC string or the ADO.NET string shown in the Somee panel."""
    if "driver=" in database_url.lower():
        return database_url
    mapped: dict[str, str] = {}
    for key, value in _connection_pairs(database_url):
        target = _ADO_TO_ODBC.get(key.lower())
        if target is None:
            continue
        if target == "TrustServerCertificate":
            value = "yes" if value.lower() in {"true", "yes", "1"} else "no"
        mapped[target] = value
    pieces = [f"DRIVER={{{driver}}}"]
    for key in ("SERVER", "DATABASE", "UID", "PWD", "TrustServerCertificate", "Packet Size", "WSID"):
        if key in mapped:
            pieces.append(f"{key}={_odbc_value(mapped[key])}")
    if "TrustServerCertificate" not in mapped:
        pieces.append("TrustServerCertificate=yes")
    return ";".join(pieces) + ";"


def _connection_pairs(database_url: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in database_url.split(";"):
        if not part.strip() or "=" not in part:
            continue
        key, value = part.split("=", 1)
        pairs.append((key.strip(), value.strip()))
    return pairs


def _odbc_value(value: str) -> str:
    if any(character in value for character in ";{}"):
        return "{" + value.replace("}", "}}") + "}"
    return value


def _row_to_event(row) -> StoredEvent:
    payload = row[4]
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return StoredEvent(
        event_id=str(row[0]),
        aggregate_id=str(row[1]),
        aggregate_type=str(row[2]),
        event_type=str(row[3]),
        payload=json.loads(payload),
        version=int(row[5]),
        occurred_at=str(row[6]),
    )
