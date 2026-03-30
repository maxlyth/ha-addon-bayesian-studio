"""Thin wrapper around the backfill project's core.py for use in Bayesian Studio."""
import importlib.util
import os
import time
from typing import Callable, Optional

_WRITE_BATCH_SIZE = 500

# Runtime path: core.py is a pyscript app installed under the HA config dir
_RUNTIME_CORE_RELPATH = os.path.join("pyscript", "apps", "backfill_bayesian", "core.py")


def _load_core(config_dir: str):
    """Load the backfill core module by file path.

    Resolution order:
    1. BACKFILL_CORE_PATH env var (tests / manual override)
    2. {config_dir}/pyscript/apps/backfill_bayesian/core.py (runtime)

    Raises ImportError if neither path exists.
    """
    env_path = os.environ.get("BACKFILL_CORE_PATH")
    candidate = env_path if env_path else os.path.join(config_dir, _RUNTIME_CORE_RELPATH)

    if not os.path.isfile(candidate):
        raise ImportError(
            f"Backfill core not found at {candidate!r}. "
            "Install the backfill pyscript app or set BACKFILL_CORE_PATH."
        )

    spec = importlib.util.spec_from_file_location("backfill_core", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_sqlite_path(config_dir: str) -> Optional[str]:
    """Return the SQLite DB file path if the recorder uses SQLite, else None."""
    from bayesian_studio.engine.database import get_db_url
    url = get_db_url(config_dir)
    if not url.startswith("sqlite:///"):
        return None
    # Strip scheme prefix; sqlite:////abs/path → /abs/path, sqlite:///rel.db → rel.db
    return url[len("sqlite:///"):]


def get_full_history_range(entity_id: str, config_dir: str) -> Optional[tuple[float, float]]:
    """Return (earliest_ts, now_ts) for the entity's full recorder history, or None."""
    db_path = get_sqlite_path(config_dir)
    if db_path is None:
        return None
    core = _load_core(config_dir)
    earliest = core.get_bayesian_window_start([entity_id], db_path)
    if earliest is None:
        return None
    return (earliest, time.time())


def run_backfill(
    entity_id: str,
    working: dict,
    timelines: dict,
    start_ts: float,
    end_ts: float,
    lat: float,
    lon: float,
    config_dir: str,
    progress_callback: Optional[Callable[[float], None]] = None,
    tz=None,
) -> dict:
    """Compute and write Bayesian probability history to the recorder DB.

    Returns {"rows_written": int, "total_seconds": float, "warnings": list}.
    Raises ImportError if the backfill core module is not available.
    Raises ValueError if DB is not SQLite or the entity has no states_meta entry.
    """
    db_path = get_sqlite_path(config_dir)
    if db_path is None:
        raise ValueError("Backfill is only supported for SQLite recorder databases.")

    core = _load_core(config_dir)
    t_start = time.time()

    result = core.compute_backfill_rows(
        working["observations"],
        working["prior"],
        working["threshold"],
        timelines,
        start_ts,
        end_ts,
        lat,
        lon,
        False,  # debug=False
        tz,
    )

    history_rows = result["history_rows"]
    if not history_rows:
        return {
            "rows_written": 0,
            "total_seconds": round(time.time() - t_start, 1),
            "warnings": result["warnings"],
        }

    metadata_id, base_attrs, old_state_id = core.prepare_history_write(
        entity_id, db_path, history_rows[0]["ts"]
    )

    total = len(history_rows)
    rows_written = 0
    prev_state_val = None

    for batch_start in range(0, total, _WRITE_BATCH_SIZE):
        batch = history_rows[batch_start:batch_start + _WRITE_BATCH_SIZE]
        inserted, old_state_id, prev_state_val = core.write_history_batch(
            batch, metadata_id, base_attrs, old_state_id, prev_state_val, db_path
        )
        rows_written += inserted
        if progress_callback:
            progress_callback(min(1.0, (batch_start + len(batch)) / total))

    return {
        "rows_written": rows_written,
        "total_seconds": round(time.time() - t_start, 1),
        "warnings": result["warnings"],
    }


def run_full_backfill(
    entity_id: str,
    working: dict,
    start_ts: float,
    end_ts: float,
    lat: float,
    lon: float,
    config_dir: str,
    progress_callback: Optional[Callable[[float], None]] = None,
    tz=None,
) -> dict:
    """Backfill full history — loads its own timelines from DB via core.py.

    Unlike run_backfill (which reuses the Studio page's timelines), this loads
    timelines directly from the DB for the full date range.
    """
    db_path = get_sqlite_path(config_dir)
    if db_path is None:
        raise ValueError("Backfill is only supported for SQLite recorder databases.")

    core = _load_core(config_dir)
    t_start = time.time()

    # Collect all entity_ids referenced by the observations
    obs_entity_ids = [
        obs["entity_id"] for obs in working["observations"] if "entity_id" in obs
    ]
    tpl_entity_ids = core.extract_template_entity_ids(working["observations"])
    all_ids = list(set(obs_entity_ids + tpl_entity_ids))

    load_attrs = any(
        "state_attr(" in obs.get("value_template", "")
        or "is_state_attr(" in obs.get("value_template", "")
        for obs in working["observations"]
    )
    timelines = core.load_state_timelines(all_ids, start_ts, end_ts, load_attrs, db_path)

    result = core.compute_backfill_rows(
        working["observations"],
        working["prior"],
        working["threshold"],
        timelines,
        start_ts,
        end_ts,
        lat,
        lon,
        False,
        tz,
    )

    history_rows = result["history_rows"]
    if not history_rows:
        return {
            "rows_written": 0,
            "total_seconds": round(time.time() - t_start, 1),
            "warnings": result["warnings"],
        }

    metadata_id, base_attrs, old_state_id = core.prepare_history_write(
        entity_id, db_path, history_rows[0]["ts"]
    )

    total = len(history_rows)
    rows_written = 0
    prev_state_val = None

    for batch_start in range(0, total, _WRITE_BATCH_SIZE):
        batch = history_rows[batch_start:batch_start + _WRITE_BATCH_SIZE]
        inserted, old_state_id, prev_state_val = core.write_history_batch(
            batch, metadata_id, base_attrs, old_state_id, prev_state_val, db_path
        )
        rows_written += inserted
        if progress_callback:
            progress_callback(min(1.0, (batch_start + len(batch)) / total))

    return {
        "rows_written": rows_written,
        "total_seconds": round(time.time() - t_start, 1),
        "warnings": result["warnings"],
    }
