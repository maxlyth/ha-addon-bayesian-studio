"""State timeline loading from the HA recorder database via SQLAlchemy."""

import bisect
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


def load_state_timelines(
    entity_ids: list[str],
    start_ts: float,
    end_ts: float,
    load_attrs: bool,
    conn: Connection,
) -> dict[str, dict]:
    """Bulk-load state histories for all entity_ids in [start_ts, end_ts].

    Queries from (start_ts - 86400) for a 1-day lookback seed for forward-fill.
    Returns {entity_id: {"ts": [...], "state": [...], "attrs": [...]}}, sorted ascending.
    "attrs" entries are raw JSON strings when load_attrs=True, else None.
    """
    if not entity_ids:
        return {}

    lookback = start_ts - 86400
    placeholders = ", ".join(f":id{i}" for i in range(len(entity_ids)))
    id_params = {f"id{i}": eid for i, eid in enumerate(entity_ids)}

    meta_rows = conn.execute(
        text(
            f"SELECT entity_id, metadata_id FROM states_meta "
            f"WHERE entity_id IN ({placeholders})"
        ),
        id_params,
    ).fetchall()

    if not meta_rows:
        return {}

    meta_id_to_entity = {r[1]: r[0] for r in meta_rows}
    meta_ids = list(meta_id_to_entity.keys())
    ph2 = ", ".join(f":mid{i}" for i in range(len(meta_ids)))
    mid_params = {f"mid{i}": mid for i, mid in enumerate(meta_ids)}

    query_params = {**mid_params, "lookback": lookback, "end_ts": end_ts}

    if load_attrs:
        rows = conn.execute(
            text(
                f"""
                SELECT s.metadata_id, s.state, s.last_updated_ts, sa.shared_attrs
                FROM states s
                LEFT JOIN state_attributes sa ON sa.attributes_id = s.attributes_id
                WHERE s.metadata_id IN ({ph2})
                  AND s.last_updated_ts >= :lookback
                  AND s.last_updated_ts <= :end_ts
                ORDER BY s.metadata_id, s.last_updated_ts
                """
            ),
            query_params,
        ).fetchall()
    else:
        rows = conn.execute(
            text(
                f"""
                SELECT s.metadata_id, s.state, s.last_updated_ts
                FROM states s
                WHERE s.metadata_id IN ({ph2})
                  AND s.last_updated_ts >= :lookback
                  AND s.last_updated_ts <= :end_ts
                ORDER BY s.metadata_id, s.last_updated_ts
                """
            ),
            query_params,
        ).fetchall()

    result: dict[str, dict] = {}
    for row in rows:
        eid = meta_id_to_entity[row[0]]
        if eid not in result:
            result[eid] = {"ts": [], "state": [], "attrs": []}
        result[eid]["ts"].append(row[2])
        result[eid]["state"].append(row[1])
        result[eid]["attrs"].append(row[3] if load_attrs else None)

    return result


def get_state_at(timeline: dict | None, ts: float) -> str | None:
    """Forward-fill: return the last known state at or before ts, or None."""
    if not timeline or not timeline["ts"]:
        return None
    idx = bisect.bisect_right(timeline["ts"], ts) - 1
    return timeline["state"][idx] if idx >= 0 else None


def get_attr_at(timeline: dict | None, ts: float, attr_name: str) -> Any:
    """Forward-fill: return the value of attr_name at or before ts, or None."""
    if not timeline or not timeline["ts"]:
        return None
    idx = bisect.bisect_right(timeline["ts"], ts) - 1
    if idx < 0:
        return None
    attrs_json = timeline["attrs"][idx]
    if not attrs_json:
        return None
    try:
        return json.loads(attrs_json).get(attr_name)
    except (json.JSONDecodeError, TypeError):
        return None
