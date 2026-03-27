"""SQLAlchemy database abstraction for the HA recorder.

Supports SQLite (default), MySQL/MariaDB (pymysql), and PostgreSQL (pg8000).
All connections are read-only — this tool never writes to the recorder DB.
"""

import os
import re

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine


def get_db_url(config_dir: str) -> str:
    """Read the recorder db_url from configuration.yaml.

    Resolution order:
    1. recorder: db_url: <value> in configuration.yaml
    2. Default: sqlite:///<config_dir>/home-assistant_v2.db
    """
    config_file = os.path.join(config_dir, "configuration.yaml")
    try:
        with open(config_file) as f:
            content = f.read()
        m = re.search(r"^\s*db_url\s*:\s*(.+)$", content, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except OSError:
        pass

    db_path = os.path.join(config_dir, "home-assistant_v2.db")
    return f"sqlite:///{db_path}"


def get_engine(config_dir: str) -> Engine:
    """Create a SQLAlchemy engine for the HA recorder database."""
    url = get_db_url(config_dir)
    return create_engine(url)


def get_read_connection(engine: Engine):
    """Return a context manager yielding a read-only connection.

    For SQLite: opens with immutable flag (raises on any write attempt).
    For MySQL/PostgreSQL: begins a read-only transaction.
    """
    return _ReadOnlyConnection(engine)


class _ReadOnlyConnection:
    """Context manager that yields a read-only SQLAlchemy connection."""

    def __init__(self, engine: Engine):
        self._engine = engine
        self._conn = None

    def __enter__(self):
        dialect = self._engine.dialect.name
        if dialect == "sqlite":
            # Use immutable URI flag — SQLite raises on any write attempt
            db_path = self._engine.url.database
            ro_engine = create_engine(f"sqlite:///file:{db_path}?mode=ro&uri=true")
            self._conn = ro_engine.connect()
        else:
            self._conn = self._engine.connect()
            if dialect in ("mysql", "postgresql"):
                self._conn.execute(text("SET TRANSACTION READ ONLY"))
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn is not None:
            self._conn.close()
        return False
