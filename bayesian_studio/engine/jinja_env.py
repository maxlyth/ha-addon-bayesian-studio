"""Jinja2 environment with historical HA state mocks for template evaluation."""

from datetime import datetime, timezone

from jinja2 import Environment, Undefined

from bayesian_studio.engine.solar import solar_elevation
from bayesian_studio.engine.state_db import get_attr_at, get_state_at


def build_jinja2_env(timelines: dict, lat: float, lon: float) -> tuple:
    """Build a Jinja2 environment with historical states()/state_attr()/now() mocks.

    Returns (env, ctx). Set ctx["ts"] to the target Unix timestamp before each render.
    state_attr("sun.sun", "elevation") is computed astronomically from lat/lon.
    """
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
        return datetime.fromtimestamp(ctx["ts"], tz=timezone.utc)

    env = Environment(undefined=Undefined)
    env.globals.update({"states": _states, "state_attr": _state_attr, "now": _now})
    return env, ctx


def eval_template(template_obj, ctx: dict) -> bool:
    """Render a pre-compiled Jinja2 template and return a bool. Returns False on error."""
    try:
        result = template_obj.render().strip().lower()
        return result in ("true", "1", "yes")
    except Exception:
        return False
