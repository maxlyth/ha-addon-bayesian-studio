"""Shared fixtures for Bayesian Studio tests."""
import json
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Minimal HA config dir factory
# ---------------------------------------------------------------------------

def _make_config_dir(tmp_path, recorder_section=""):
    """Create a minimal HA config directory with core.config and configuration.yaml."""
    storage = tmp_path / ".storage"
    storage.mkdir()

    (storage / "core.config").write_text(json.dumps({
        "data": {"latitude": 51.5, "longitude": -0.1, "time_zone": "UTC"}
    }))

    cfg = "homeassistant:\n  name: Test\n"
    if recorder_section:
        cfg += recorder_section
    (tmp_path / "configuration.yaml").write_text(cfg)

    return str(tmp_path)


@pytest.fixture
def config_dir(tmp_path):
    """Config dir with no explicit recorder db_url (defaults to SQLite)."""
    return _make_config_dir(tmp_path)


@pytest.fixture
def config_dir_with_mysql(tmp_path):
    """Config dir with a MySQL recorder db_url."""
    section = "recorder:\n  db_url: mysql+pymysql://user:pass@localhost/homeassistant\n"
    return _make_config_dir(tmp_path, recorder_section=section)


@pytest.fixture
def config_dir_with_postgres(tmp_path):
    """Config dir with a PostgreSQL recorder db_url."""
    section = "recorder:\n  db_url: postgresql+pg8000://user:pass@localhost/homeassistant\n"
    return _make_config_dir(tmp_path, recorder_section=section)


# ---------------------------------------------------------------------------
# In-memory SQLite DB with the HA recorder schema (modern, post-2024.1)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS states_meta (
    metadata_id INTEGER PRIMARY KEY,
    entity_id   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS state_attributes (
    attributes_id INTEGER PRIMARY KEY,
    hash          INTEGER NOT NULL,
    shared_attrs  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS states (
    state_id        INTEGER PRIMARY KEY,
    metadata_id     INTEGER NOT NULL,
    state           TEXT,
    last_updated_ts REAL NOT NULL,
    last_changed_ts REAL,
    last_reported_ts REAL,
    old_state_id    INTEGER,
    attributes_id   INTEGER,
    context_id_bin  BLOB,
    origin_idx      INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_states_meta_entity_id ON states_meta (entity_id);
CREATE INDEX IF NOT EXISTS ix_states_metadata_ts
    ON states (metadata_id, last_updated_ts);
"""


def make_states_db(path):
    """Create a recorder-schema SQLite DB at path and return its path string."""
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def states_db(config_dir):
    """Empty recorder-schema SQLite DB inside the config_dir fixture."""
    import os
    return make_states_db(os.path.join(config_dir, "home-assistant_v2.db"))


def insert_states(db_path, entity_id, rows):
    """Helper: insert (ts, state) rows for entity_id into a test DB."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO states_meta (entity_id) VALUES (?)", (entity_id,)
    )
    meta_id = conn.execute(
        "SELECT metadata_id FROM states_meta WHERE entity_id = ?", (entity_id,)
    ).fetchone()[0]
    for ts, state in rows:
        conn.execute(
            "INSERT INTO states (metadata_id, state, last_updated_ts) VALUES (?,?,?)",
            (meta_id, state, ts),
        )
    conn.commit()
    conn.close()
