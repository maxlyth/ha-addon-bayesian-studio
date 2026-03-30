"""Jinja2 environment with historical HA state mocks for template evaluation."""

import math
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional

from jinja2 import Environment, Undefined

from bayesian_studio.engine.solar import solar_elevation
from bayesian_studio.engine.state_db import get_attr_at, get_state_at


def build_jinja2_env(
    timelines: dict, lat: float, lon: float, tz: Optional[tzinfo] = None
) -> tuple:
    """Build a Jinja2 environment with historical states()/state_attr()/now() mocks.

    Returns (env, ctx). Set ctx["ts"] to the target Unix timestamp before each render.
    state_attr("sun.sun", "elevation") is computed astronomically from lat/lon.
    tz: timezone for now(); defaults to UTC if not provided.
    """
    _tz = tz or timezone.utc
    ctx = {"ts": 0.0}

    def _states(entity_id):
        tl = timelines.get(entity_id)
        if tl is None:
            return "unknown"
        state = get_state_at(tl, ctx["ts"])
        return state if state is not None else "unknown"

    def _state_attr(entity_id, attribute):
        if entity_id == "sun.sun" and attribute == "elevation":
            return solar_elevation(ctx["ts"], lat, lon)
        tl = timelines.get(entity_id)
        if tl is None:
            return None
        return get_attr_at(tl, ctx["ts"], attribute)

    def _now():
        return datetime.fromtimestamp(ctx["ts"], tz=_tz)

    def _is_state(entity_id, state):
        return _states(entity_id) == str(state)

    def _is_state_attr(entity_id, attribute, value):
        return _state_attr(entity_id, attribute) == value

    def _has_value(entity_id):
        tl = timelines.get(entity_id)
        if tl is None:
            return False
        state = get_state_at(tl, ctx["ts"])
        return state not in (None, "unavailable", "unknown")

    def _utcnow():
        return datetime.fromtimestamp(ctx["ts"], tz=timezone.utc)

    def _today_at(time_string="00:00"):
        parts = time_string.split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        s = int(parts[2]) if len(parts) > 2 else 0
        local_now = datetime.fromtimestamp(ctx["ts"], tz=_tz)
        return local_now.replace(hour=h, minute=m, second=s, microsecond=0)

    def _as_timestamp(value, default=None):
        try:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, datetime):
                return value.timestamp()
            if isinstance(value, str):
                return datetime.fromisoformat(value).timestamp()
        except (ValueError, TypeError, OSError):
            pass
        return default

    def _as_datetime(value, default=None):
        try:
            if isinstance(value, datetime):
                return value
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value, tz=_tz)
            if isinstance(value, str):
                return datetime.fromisoformat(value)
        except (ValueError, TypeError, OSError):
            pass
        return default

    def _as_local(value):
        if isinstance(value, datetime):
            return value.astimezone(_tz)
        return value

    def _strptime(string, fmt, default=None):
        try:
            return datetime.strptime(string, fmt)
        except (ValueError, TypeError):
            if default is not None:
                return default
            raise

    def _ha_float(value, default=None):
        try:
            return float(value)
        except (ValueError, TypeError):
            if default is not None:
                return default
            raise

    def _ha_int(value, default=None):
        try:
            return int(float(value))
        except (ValueError, TypeError):
            if default is not None:
                return default
            raise

    def _ha_bool(value, default=None):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower = value.lower()
            if lower in ("true", "yes", "on", "enable", "1"):
                return True
            if lower in ("false", "no", "off", "disable", "0"):
                return False
        if default is not None:
            return default
        raise ValueError(f"Cannot convert {value!r} to bool")

    def _is_number(value):
        try:
            fval = float(value)
            return not (math.isinf(fval) or math.isnan(fval))
        except (ValueError, TypeError):
            return False

    def _iif(condition, if_true=True, if_false="", if_none=None):
        if condition is None and if_none is not None:
            return if_none
        return if_true if condition else if_false

    class _StatesProxy:
        """Callable proxy supporting both states('entity') and states.domain.name."""

        def __call__(self, entity_id):
            return _states(entity_id)

        def __getattr__(self, domain):
            class _DomainProxy:
                def __getattr__(_, name):
                    return _states(f"{domain}.{name}")
            return _DomainProxy()

    env = Environment(undefined=Undefined)
    env.globals.update({
        "states": _StatesProxy(),
        "state_attr": _state_attr,
        "now": _now,
        "utcnow": _utcnow,
        "today_at": _today_at,
        "as_timestamp": _as_timestamp,
        "as_datetime": _as_datetime,
        "as_local": _as_local,
        "strptime": _strptime,
        "timedelta": timedelta,
        "float": _ha_float,
        "int": _ha_int,
        "bool": _ha_bool,
        "is_state": _is_state,
        "is_state_attr": _is_state_attr,
        "has_value": _has_value,
        "is_number": _is_number,
        "iif": _iif,
    })
    env.filters.update({
        "float": _ha_float,
        "int": _ha_int,
        "bool": _ha_bool,
        "is_number": _is_number,
        "as_timestamp": _as_timestamp,
        "as_datetime": _as_datetime,
        "as_local": _as_local,
        "iif": _iif,
    })
    return env, ctx


def eval_template(template_obj, ctx: dict) -> bool:
    """Render a pre-compiled Jinja2 template and return a bool. Returns False on error."""
    try:
        result = template_obj.render().strip().lower()
        return result in ("true", "1", "yes")
    except Exception:
        return False
