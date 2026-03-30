"""Tests for bayesian_studio.engine.backfill."""
import os
from unittest.mock import MagicMock, patch

import pytest

from bayesian_studio.engine.backfill import (
    _load_core,
    get_sqlite_path,
    run_backfill,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_core(n_rows: int = 3):
    core = MagicMock()
    rows = [{"ts": float(1000 + i), "probability": 0.7, "state": "on"} for i in range(n_rows)]
    core.compute_backfill_rows.return_value = {
        "history_rows": rows,
        "warnings": [],
    }
    core.prepare_history_write.return_value = [42, {"probability": 0.5}, None]
    # write_history_batch returns [inserted, old_state_id, prev_state_val]
    core.write_history_batch.return_value = [n_rows, 99, "on"]
    return core


_WORKING = {
    "observations": [{"platform": "state", "entity_id": "binary_sensor.x",
                      "to_state": "on", "prob_given_true": 0.9, "prob_given_false": 0.1}],
    "prior": 0.5,
    "threshold": 0.5,
}

_TIMELINES = {
    "binary_sensor.x": {"ts": [1000.0], "state": ["on"], "attrs": [None]}
}


# ---------------------------------------------------------------------------
# get_sqlite_path
# ---------------------------------------------------------------------------

class TestGetSqlitePath:
    def test_returns_path_for_sqlite_url(self, tmp_path):
        db = tmp_path / "ha.db"
        with patch("bayesian_studio.engine.backfill.get_sqlite_path") as _p:
            pass  # just verify import works

    def test_sqlite_url_extraction(self, tmp_path):
        with patch("bayesian_studio.engine.database.get_db_url", return_value="sqlite:////config/ha.db"):
            result = get_sqlite_path("/config")
        assert result == "/config/ha.db"

    def test_returns_none_for_mysql(self, tmp_path):
        with patch("bayesian_studio.engine.database.get_db_url",
                   return_value="mysql+pymysql://user:pass@localhost/ha"):
            result = get_sqlite_path("/config")
        assert result is None

    def test_returns_none_for_postgres(self):
        with patch("bayesian_studio.engine.database.get_db_url",
                   return_value="postgresql+pg8000://user:pass@localhost/ha"):
            result = get_sqlite_path("/config")
        assert result is None


# ---------------------------------------------------------------------------
# _load_core
# ---------------------------------------------------------------------------

class TestLoadCore:
    def test_raises_import_error_when_not_found(self, tmp_path):
        with patch.dict("os.environ", {}, clear=True):
            os.environ.pop("BACKFILL_CORE_PATH", None)
            with pytest.raises(ImportError, match="not found"):
                _load_core(str(tmp_path))

    def test_loads_from_env_var(self, tmp_path):
        # Write a minimal fake core.py
        core_file = tmp_path / "core.py"
        core_file.write_text("def compute_backfill_rows(*a, **kw): return {}")
        with patch.dict("os.environ", {"BACKFILL_CORE_PATH": str(core_file)}):
            mod = _load_core("/any/path")
        assert hasattr(mod, "compute_backfill_rows")

    def test_loads_from_runtime_path(self, tmp_path):
        core_dir = tmp_path / "pyscript" / "apps" / "backfill_bayesian"
        core_dir.mkdir(parents=True)
        (core_dir / "core.py").write_text("VERSION = '0.3.0'")
        with patch.dict("os.environ", {}, clear=True):
            os.environ.pop("BACKFILL_CORE_PATH", None)
            mod = _load_core(str(tmp_path))
        assert mod.VERSION == "0.3.0"


# ---------------------------------------------------------------------------
# run_backfill
# ---------------------------------------------------------------------------

class TestRunBackfill:
    def _run(self, core, n_rows=3, progress_calls=None):
        calls = []
        with patch("bayesian_studio.engine.backfill._load_core", return_value=core):
            with patch("bayesian_studio.engine.backfill.get_sqlite_path", return_value="/config/ha.db"):
                result = run_backfill(
                    entity_id="binary_sensor.test",
                    working=_WORKING,
                    timelines=_TIMELINES,
                    start_ts=900.0,
                    end_ts=2000.0,
                    lat=51.5,
                    lon=-0.1,
                    config_dir="/config",
                    progress_callback=calls.append if progress_calls is not None else None,
                )
        if progress_calls is not None:
            progress_calls.extend(calls)
        return result

    def test_returns_rows_written(self):
        core = _fake_core(n_rows=3)
        result = self._run(core)
        assert result["rows_written"] == 3

    def test_compute_backfill_rows_called(self):
        core = _fake_core()
        self._run(core)
        core.compute_backfill_rows.assert_called_once()

    def test_prepare_history_write_called_with_entity(self):
        core = _fake_core()
        self._run(core)
        args = core.prepare_history_write.call_args[0]
        assert args[0] == "binary_sensor.test"

    def test_write_history_batch_called(self):
        core = _fake_core()
        self._run(core)
        core.write_history_batch.assert_called()

    def test_progress_callback_called(self):
        core = _fake_core(n_rows=3)
        progress_calls = []
        self._run(core, progress_calls=progress_calls)
        assert len(progress_calls) >= 1
        assert all(0.0 <= v <= 1.0 for v in progress_calls)

    def test_empty_history_rows_returns_zero(self):
        core = MagicMock()
        core.compute_backfill_rows.return_value = {"history_rows": [], "warnings": []}
        result = self._run(core)
        assert result["rows_written"] == 0
        core.prepare_history_write.assert_not_called()

    def test_raises_value_error_for_non_sqlite(self):
        core = _fake_core()
        with patch("bayesian_studio.engine.backfill._load_core", return_value=core):
            with patch("bayesian_studio.engine.backfill.get_sqlite_path", return_value=None):
                with pytest.raises(ValueError, match="SQLite"):
                    run_backfill(
                        entity_id="binary_sensor.test",
                        working=_WORKING,
                        timelines=_TIMELINES,
                        start_ts=900.0,
                        end_ts=2000.0,
                        lat=0.0,
                        lon=0.0,
                        config_dir="/config",
                    )

    def test_total_seconds_is_float(self):
        core = _fake_core()
        result = self._run(core)
        assert isinstance(result["total_seconds"], float)

    def test_warnings_forwarded(self):
        core = _fake_core()
        core.compute_backfill_rows.return_value = {
            "history_rows": [{"ts": 1000.0, "probability": 0.7, "state": "on"}],
            "warnings": [{"type": "always_active", "detail": "test"}],
        }
        core.prepare_history_write.return_value = [42, {}, None]
        core.write_history_batch.return_value = [1, 99, "on"]
        result = self._run(core)
        assert len(result["warnings"]) == 1
