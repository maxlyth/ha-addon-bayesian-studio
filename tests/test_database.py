"""TDD tests for bayesian_studio.engine.database."""
import pytest
from sqlalchemy import text

from bayesian_studio.engine.database import get_db_url, get_engine, get_read_connection


class TestGetDbUrl:
    def test_defaults_to_sqlite_when_no_recorder_block(self, config_dir):
        url = get_db_url(config_dir)
        assert "sqlite" in url
        assert "home-assistant_v2.db" in url

    def test_returns_explicit_mysql_url(self, config_dir_with_mysql):
        url = get_db_url(config_dir_with_mysql)
        assert url == "mysql+pymysql://user:pass@localhost/homeassistant"

    def test_returns_explicit_postgres_url(self, config_dir_with_postgres):
        url = get_db_url(config_dir_with_postgres)
        assert url == "postgresql+pg8000://user:pass@localhost/homeassistant"


class TestGetEngine:
    def test_creates_sqlite_engine(self, config_dir, states_db):
        engine = get_engine(config_dir)
        assert engine is not None
        assert "sqlite" in str(engine.url)

    def test_engine_can_query(self, config_dir, states_db):
        engine = get_engine(config_dir)
        with get_read_connection(engine) as conn:
            result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1


class TestGetReadConnection:
    def test_connection_is_read_only_for_sqlite(self, config_dir, states_db):
        engine = get_engine(config_dir)
        with get_read_connection(engine) as conn:
            with pytest.raises(Exception):
                conn.execute(text("CREATE TABLE _test_write (x INTEGER)"))
                conn.commit()

    def test_can_read_states_meta(self, config_dir, states_db):
        import os
        from tests.conftest import insert_states
        insert_states(states_db, "binary_sensor.test", [(1000.0, "on")])
        engine = get_engine(config_dir)
        with get_read_connection(engine) as conn:
            row = conn.execute(
                text("SELECT entity_id FROM states_meta WHERE entity_id = :eid"),
                {"eid": "binary_sensor.test"},
            ).fetchone()
        assert row is not None
        assert row[0] == "binary_sensor.test"
