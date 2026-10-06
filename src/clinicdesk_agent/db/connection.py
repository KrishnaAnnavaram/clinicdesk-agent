"""SQLite access with separate read-only and read-write connections.

Code that serves the language model's *read* tools only ever receives a
connection opened with ``mode=ro`` and ``PRAGMA query_only``, so even a bug
there cannot modify data. Writes go through :func:`transaction`, which uses
``BEGIN IMMEDIATE`` so concurrent bookers are serialised by SQLite.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator


def _schema_sql() -> str:
    return resources.files("clinicdesk_agent.db").joinpath("schema.sql").read_text(encoding="utf-8")


class Database:
    """Factory for connections to one SQLite file."""

    def __init__(self, path: Path | str, *, busy_timeout_ms: int = 10_000) -> None:
        self.path = Path(path).expanduser().resolve()
        self.busy_timeout_ms = busy_timeout_ms

    def _configure(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        return conn

    def initialise(self) -> None:
        """Create the parent folder and all tables (idempotent)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.writer() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_schema_sql())

    @contextmanager
    def writer(self) -> Iterator[sqlite3.Connection]:
        # isolation_level=None: autocommit; transactions are opened explicitly.
        conn = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000, isolation_level=None)
        try:
            yield self._configure(conn)
        finally:
            conn.close()

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        if not self.path.exists():
            raise FileNotFoundError(f"database not found at {self.path}; run `clinicdesk init-db` first")
        uri = f"{self.path.as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=self.busy_timeout_ms / 1000, isolation_level=None)
        try:
            self._configure(conn)
            conn.execute("PRAGMA query_only = ON")
            yield conn
        finally:
            conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside ``BEGIN IMMEDIATE`` ... ``COMMIT``; roll back on any error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
