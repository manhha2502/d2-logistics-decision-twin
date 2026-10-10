"""
actions.py — Apply Scenario actions to the simulation (Task 6).

Every action changes the simulated system; none is just a label:

  REASSIGN_AMR              moves `count` available AMRs from_route -> to_route at
                            start_time and reverts after duration_min (if given).
  PRIORITIZE_REQUEST        matching requests (route / material_id) jump the picker
                            queue and the AMR dispatch order inside the window.
                            (Limitation: only affects unassigned requests; requests
                            already grabbed by Picker/AMR are not interrupted).
  ADJUST_REPLENISHMENT_TIME requests needed inside the window are released
                            `shift_min` earlier (more lead time, same need time).
  CONSOLIDATE_DELIVERY      inside the window one AMR trip carries several staged
                            requests of the route up to payload (or max_batch_totes).
  ALTERNATE_ROUTE           only effective if `to_route` really exists in route_master
                            AND shares the destination of `from_route`.  The simulator
                            never creates a route; otherwise it is ignored and reported
                            as NO_ALTERNATIVE_ROUTE_CONFIGURED.

Timing lives in Action.parameters: start_time (absolute), duration_min.
Optional parameters per action are read with .get(); nothing is added to the schema.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

import simpy

from src.common.schemas import Action, Scenario

if TYPE_CHECKING:
    from .entities import MaterialRequest
    from .environment import SimulationEnvironment

INF = math.inf
KNOWN_ACTIONS = {
    "REASSIGN_AMR", "PRIORITIZE_REQUEST", "ADJUST_REPLENISHMENT_TIME",
    "CONSOLIDATE_DELIVERY", "ALTERNATE_ROUTE",
}


@dataclass
class _Window:
    start: float
    end: float
    route: Optional[str] = None
    material: Optional[str] = None
    value: float = 0.0
    extra: dict = field(default_factory=dict)

    def active(self, t: float) -> bool:
        return self.start - 1e-9 <= t < self.end


@dataclass
class ActionPlan:
    priority: list[_Window] = field(default_factory=list)
    consolidate: list[_Window] = field(default_factory=list)
    replenish: list[_Window] = field(default_factory=list)
    alternate: list[_Window] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)

    # ---- queries used by processes --------------------------------------
    def priority_of(self, req: "MaterialRequest", t: float) -> int:
        """0 = prioritised, 1 = normal (lower is served first)."""
        for w in self.priority:
            if w.active(t) and (w.route in (None, req.route)) and (w.material in (None, req.material_id)):
                return 0
        return 1

    def max_batch(self, route: str, t: float) -> Optional[float]:
        """None = consolidation off; otherwise max totes per consolidated trip (inf = payload)."""
        for w in self.consolidate:
            if w.route in (None, route) and w.active(t):
                return w.value if w.value > 0 else INF
        return None

    def release_shift(self, route: str, need_time: float) -> float:
        best = 0.0
        for w in self.replenish:
            if w.route in (None, route) and w.active(need_time):
                best = max(best, w.value)
        return best


# ---------------------------------------------------------------------------
def _window(action: Action, sim_env: "SimulationEnvironment", horizon: float) -> tuple[float, float]:
    p = action.parameters
    start = 0.0
    raw = p.get("start_time")
    if raw == "NOW":
        start = 0.0
    elif raw:
        off = sim_env.conditions.offset_min(raw) if sim_env.conditions is not None else None
        if off is not None:
            start = max(0.0, off)
    dur = float(p.get("duration_min", 0) or 0)
    return start, (start + dur if dur > 0 else INF)


def apply_actions(
    env: simpy.Environment,
    sim_env: "SimulationEnvironment",
    scenario: Scenario,
    sim_start: Optional[datetime] = None,   # kept for API compatibility; offsets come from conditions
) -> ActionPlan:
    """Resolve scenario actions into an ActionPlan and register timed processes."""
    plan = ActionPlan()
    sim_env.actions = plan
    main = sim_env.sys_cfg["routes"]["main"]
    horizon = float(sim_env.sys_cfg["simulation"]["horizon_min"])
    if not scenario or not scenario.actions:
        return plan

    for action in scenario.actions:
        p = action.parameters
        atype = action.action_type
        start, end = _window(action, sim_env, horizon)
        
        used_keys = {"start_time", "duration_min"}

        def _get(*keys, default=None):
            # Mark every alias as "used" so a caller passing several
            # equivalent names (e.g. both `route` and `target_line`) does not
            # trigger a spurious UNKNOWN_PARAMS warning for the unused ones.
            for k in keys:
                used_keys.add(k)
            for k in keys:
                if k in p:
                    return p[k]
            return default

        if atype not in KNOWN_ACTIONS:
            plan.ignored.append({"action_id": action.action_id, "type": atype, "reason": "UNKNOWN_ACTION_TYPE"})
            continue
        if start >= horizon:
            plan.ignored.append({"action_id": action.action_id, "type": atype, "reason": "STARTS_AFTER_HORIZON"})
            continue

        if atype == "REASSIGN_AMR":
            frm = _get("from_route", "target_route")
            to = _get("to_route", "alternate_route_id")
            count = int(_get("count", default=1))
            if frm not in sim_env.routes or to not in sim_env.routes or frm == to:
                plan.ignored.append({"action_id": action.action_id, "type": atype, "reason": "INVALID_ROUTES"})
                continue
            env.process(_reassign_amr(env, sim_env, action.action_id, frm, to, count, start, end))
            plan.applied.append(action.action_id)

        elif atype == "PRIORITIZE_REQUEST":
            route = _get("route", "target_route", "target_line", default=main)
            mat = _get("material_id")
            plan.priority.append(_Window(start, end, route, mat))
            plan.applied.append(action.action_id)

        elif atype == "ADJUST_REPLENISHMENT_TIME":
            route = _get("route", "target_route", "target_line", default=main)
            shift = float(_get("shift_min", "shift_minutes", "advance_min", 
                               default=(sim_env.sys_cfg.get("simulation") or {}).get("default_replenishment_shift_min", 5.0)))
            plan.replenish.append(_Window(start, end, route, None, max(0.0, shift)))
            plan.applied.append(action.action_id)

        elif atype == "CONSOLIDATE_DELIVERY":
            route = _get("route", "target_route", "target_line", default=main)
            batch = float(_get("max_batch_totes", "batch_size_totes", default=0) or 0)
            plan.consolidate.append(_Window(start, end, route, None, batch))
            plan.applied.append(action.action_id)

        elif atype == "ALTERNATE_ROUTE":
            frm = _get("from_route", "target_route", default=main)
            to = _get("to_route", "alternate_route_id")
            share = float(_get("share", default=1.0))
            r_from, r_to = sim_env.routes.get(frm), sim_env.routes.get(to)
            if r_from is None or r_to is None or frm == to or not r_to.destination \
                    or r_to.destination != r_from.destination:
                plan.ignored.append({"action_id": action.action_id, "type": atype,
                                     "reason": "NO_ALTERNATIVE_ROUTE_CONFIGURED"})
                continue
            plan.alternate.append(_Window(start, end, frm, None, share, {"to": to}))
            plan.applied.append(action.action_id)

        unknown = set(p.keys()) - used_keys
        if unknown and sim_env.conditions is not None:
            sim_env.conditions.warnings.append(f"{action.action_id} ignored UNKNOWN_PARAMS: {list(unknown)}")
            
    return plan


# ---------------------------------------------------------------------------
def _reassign_amr(env, sim_env, action_id: str, frm: str, to: str, count: int, start: float, end: float):
    from .processes import dispatch   # local import: avoid circularity

    if start > env.now:
        yield env.timeout(start - env.now)

    # deterministic pick: idle AMRs first, then by id; never an unavailable one
    pool = sorted((a for a in sim_env.amrs.values() if a.route == frm and a.available),
                  key=lambda a: (a.on_trip, a.amr_id))
    moved = pool[:max(0, count)]
    for a in moved:
        a.route = to
    entry = {"action_id": action_id, "t": env.now, "amrs": [a.amr_id for a in moved],
             "from": frm, "to": to, "reverted_at": None}
    sim_env.reassign_log.append(entry)
    dispatch(sim_env)

    if end < INF:
        yield env.timeout(max(0.0, end - env.now))
        for a in moved:
            if a.route == to:
                a.route = frm
        entry["reverted_at"] = env.now
        dispatch(sim_env)
