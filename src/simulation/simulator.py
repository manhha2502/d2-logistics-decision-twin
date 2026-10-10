"""
simulator.py — Public API of the SimPy What-if Digital Twin (Task 9).

    run_simulation(current_state, future_condition, scenario, seed=42) -> SimulationResult
    run_scenarios(current_state, future_condition, scenarios, seed=42)  -> list[SimulationResult]

Rules enforced
--------------
* Thresholds / capacities from YAML + master CSV (defaults only in conditions.DEFAULTS).
* Randomness: one `random.Random(seed)` that builds the request schedule *before* any
  scenario effect, so S0 and every scenario see identical arrivals (common random
  numbers).  No global RNG is touched.
* Expected = P50, Adverse = P90, Favorable = P10 (condition_mode).
* Known maintenance is applied directly; adverse mode may remove one more R1 AMR
  when secondary_bottleneck.adverse_reduce_amr is true (never below 0).
* S0 = Scenario with no actions.  Simulator never creates routes.
* `secondary_bottleneck` = R2 became critical (utilisation or waiting above the
  thresholds) where it was not critical in S0 (run_scenarios) — see _r2_state().
  run_simulation alone reports the absolute flag (R2 critical); the pipeline calls it
  per scenario and constraints.py skips S0, so the flag works without a baseline.
"""
from __future__ import annotations

import copy
import random
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd
import simpy
import yaml

from src.common.schemas import Scenario, SimulationResult
from .actions import apply_actions
from .conditions import build_conditions, sim_param
from .environment import SimulationEnvironment
from .metrics import SimulationMetrics
from .processes import (
    availability_process,
    build_request_schedule,
    production_consumption_process,
    queue_monitor_process,
    request_flow,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Config / data helpers
# ---------------------------------------------------------------------------
def _load_yaml(path: str) -> dict:
    with open(_PROJECT_ROOT / path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(_PROJECT_ROOT / path, encoding="utf-8-sig")


def _load_configs() -> tuple[dict, dict]:
    return _load_yaml("config/system.yaml"), _load_yaml("config/thresholds.yaml")


def _compat_sys_cfg(sys_cfg: dict) -> dict:
    """Adapt Hạ's runtime config to the flat system.yaml shape Phú's code expects.

    * Runtime config (keys `system`, `thresholds`, `paths`...) -> use `config["system"]`
      so the `simulation:` section of system.yaml is really read; absolute runtime
      `paths` win over the relative ones.
    * Never mutates the caller's config (the pipeline shares it across calls).
    * No numeric fallbacks here: missing values surface in conditions.build_conditions().
    """
    if isinstance(sys_cfg.get("system"), dict):
        cfg = copy.deepcopy(sys_cfg["system"])
        cfg["paths"] = {**(cfg.get("paths") or {}), **{k: v for k, v in (sys_cfg.get("paths") or {}).items() if v}}
    else:
        cfg = copy.deepcopy(sys_cfg)
    sim = cfg.setdefault("simulation", {})
    sim.setdefault("horizon_min", cfg.get("horizon_min", 60))
    sim.setdefault("interval_min", cfg.get("interval_min", 15))
    sim.setdefault("default_seed", cfg.get("seed", 42))
    if "routes" not in cfg:
        cfg["routes"] = {
            "main": cfg.get("target_route", "R1"),
            "auxiliary": "R2",
            "picker_station": "PICK",
            "line_buffer_station": "LINE_A_BUF",
            "staging_r1": "STG_R1",
        }
    return cfg


_QUANTILE_TO_MODE = {"p10": "favorable", "p50": "expected", "p90": "adverse"}
_MODES = ("favorable", "expected", "adverse")


def _resolve_condition_mode(explicit: Optional[str], future_condition: Any) -> str:
    """Condition = explicit kwarg, else future_condition["condition"], else its "quantile".
    All sources that are present must agree; none present -> "expected" (P50)."""
    found = {}
    if explicit is not None:
        found["condition_mode"] = explicit
    if isinstance(future_condition, dict):
        if future_condition.get("condition") is not None:
            found["condition"] = future_condition["condition"]
        q = future_condition.get("quantile")
        if q is not None:
            if str(q).lower() not in _QUANTILE_TO_MODE:
                raise ValueError(f"quantile must be p10/p50/p90, got {q!r}")
            found["quantile"] = _QUANTILE_TO_MODE[str(q).lower()]
    for k, v in found.items():
        if v not in _MODES:
            raise ValueError(f"{k} must be one of {_MODES}, got {v!r}")
    if len(set(found.values())) > 1:
        raise ValueError(f"Conflicting condition inputs: {found}")
    return next(iter(found.values()), "expected")


def _load_master_data(sys_cfg: dict):
    p = sys_cfg["paths"]
    if "master_dir" in p:
        md = Path(p["master_dir"])
        return (_load_csv(md / "resource_master.csv"), _load_csv(md / "route_master.csv"),
                _load_csv(md / "station_master.csv"), _load_csv(p["current_state"]),
                _load_csv(md / "material_master.csv"))
    return (_load_csv(p["master_resource"]), _load_csv(p["master_route"]),
            _load_csv(p["master_station"]), _load_csv(p["current_state"]),
            _load_csv(p["master_material"]))


def _thr(thr_cfg: dict, sys_cfg: dict) -> dict:
    sim = thr_cfg.get("simulation", {})
    sec = sys_cfg.get("secondary_bottleneck", {})
    late = float(sim.get("late_delivery_threshold_min", 20.0))
    return {
        "late": late,
        "r2_util": float(sim.get("secondary_bottleneck_utilization", sec.get("utilization_threshold", 0.80))),
        "r2_wait": float(sim.get("secondary_bottleneck_wait_min", late)),
        "worsen": float(sim.get("secondary_bottleneck_worsening", 0.05)),
    }


# ---------------------------------------------------------------------------
def _r2_state(sim_env: SimulationEnvironment, m: SimulationMetrics, aux: str, horizon: float, thr: dict) -> dict:
    pool = m.pool_minutes.get(aux, 0.0)
    busy = m.busy_by_route.get(aux, 0.0)
    has_demand = any(r.route == aux for r in m.requests)
    util = min(1.0, busy / pool) if pool > 1e-9 else (1.0 if has_demand else 0.0)
    wait = m.avg_wait(aux, horizon)
    return {
        "r2_utilization": round(util, 4),
        "r2_avg_wait": round(wait, 3),
        "r2_max_queue": round(m.max_queue(aux), 3),
        "r2_pool_amr_avg": round(pool / horizon, 3),
        "r2_critical": bool(util > thr["r2_util"] or wait > thr["r2_wait"]),
    }


def run_simulation(
    current_state: Any,
    future_condition: Any,
    scenario: Scenario,
    seed: int = 42,
    condition_mode: Optional[str] = None,
    sys_cfg: Optional[dict] = None,
    thr_cfg: Optional[dict] = None,
    resource_df: Optional[pd.DataFrame] = None,
    route_df: Optional[pd.DataFrame] = None,
    station_df: Optional[pd.DataFrame] = None,
    current_df: Optional[pd.DataFrame] = None,
    material_df: Optional[pd.DataFrame] = None,
    known_events: Any = None,
    production_plan: Any = None,
    sim_start: Optional[datetime] = None,
) -> SimulationResult:
    """Run one SimPy simulation.  See module docstring for semantics.

    current_state    DataFrame (entity_type, entity_id, metric, value) or None -> current_state.csv
    future_condition list[ForecastPoint] / list[FutureState] / dict(forecasts, future_states,
                     known_events, production_plan, sim_start) / None (history baseline + known events)
    """
    if sys_cfg is None:
        if isinstance(future_condition, dict) and "config" in future_condition:
            sys_cfg = future_condition["config"]
        else:
            sys_cfg = _load_configs()[0]
    if thr_cfg is None:
        if isinstance(future_condition, dict) and "config" in future_condition:
            cfg_raw = future_condition["config"]
            thr_cfg = cfg_raw.get("thresholds") if isinstance(cfg_raw, dict) else None
            if thr_cfg is None:
                thr_cfg = _load_configs()[1]
    else:
        thr_cfg = _load_configs()[1]
    sys_cfg = _compat_sys_cfg(sys_cfg)
    condition_mode = _resolve_condition_mode(condition_mode, future_condition)

    if current_df is None and isinstance(current_state, pd.DataFrame):
        current_df = current_state
    if any(x is None for x in (resource_df, route_df, station_df, current_df, material_df)):
        loaded = _load_master_data(sys_cfg)
        resource_df, route_df, station_df, current_df, material_df = (
            x if x is not None else y for x, y in zip(
                (resource_df, route_df, station_df, current_df, material_df), loaded))
    thr = _thr(thr_cfg, sys_cfg)

    horizon = float(sys_cfg["simulation"]["horizon_min"])
    main, aux = sys_cfg["routes"]["main"], sys_cfg["routes"]["auxiliary"]

    env = simpy.Environment()
    sim_env = SimulationEnvironment(env, sys_cfg, thr_cfg)
    sim_env.load_from_master(resource_df, route_df, station_df, current_df, material_df)
    metrics = SimulationMetrics(late_threshold_min=thr["late"])
    sim_env.metrics = metrics

    cond = build_conditions(
        future_condition, condition_mode, sys_cfg, route_df,
        sorted(sim_env.line_buffers), sim_env.amr_ids_by_route(),
        known_events=known_events, production_plan=production_plan, sim_start=sim_start,
        base_unavailable=[a.amr_id for a in sim_env.amrs.values() if not a.base_available],
    )
    sim_env.conditions = cond

    # Adverse: optionally lose one more R1 AMR (config), never below 0
    if condition_mode == "adverse" and (sys_cfg.get("secondary_bottleneck") or {}).get("adverse_reduce_amr", False):
        live = sorted((a for a in sim_env.amrs.values() if a.home_route == main and a.available), key=lambda a: a.amr_id)
        if live:
            live[-1].set_available(0.0, False)
            live[-1].base_available = False

    plan = apply_actions(env, sim_env, scenario, cond.sim_start)

    rng = random.Random(seed)
    schedule = build_request_schedule(sim_env, rng)
    for w in cond.maintenance:
        env.process(availability_process(sim_env, w))
    for r in schedule:
        metrics.register_request(r)
        env.process(request_flow(sim_env, r))
    env.process(production_consumption_process(sim_env))
    env.process(queue_monitor_process(sim_env))

    env.run(until=horizon + 1e-6)

    # ---- finalize ---------------------------------------------------------
    for a in sim_env.amrs.values():
        if a.on_trip and a.trip_start is not None:           # trip cut by the horizon
            part = horizon - a.trip_start
            a.busy_time += part
            metrics.busy_by_route[a.trip_route] = metrics.busy_by_route.get(a.trip_route, 0.0) + part
        if not a.available and a.unavailable_since is not None:
            a.unavailable_time += horizon - a.unavailable_since

    amr_util = {}
    for a in sim_env.amrs.values():
        avail_min = max(0.0, horizon - a.unavailable_time)
        amr_util[a.amr_id] = round(min(1.0, a.busy_time / avail_min), 4) if avail_min > 1e-9 else 0.0

    r2 = _r2_state(sim_env, metrics, aux, horizon, thr)

    r1_requests = [r for r in schedule if r.route == main]
    picker_util = min(1.0, metrics.picker_busy_time / (horizon * sim_env.picker.capacity))
    if picker_util >= 0.9:
        cond.warnings.append(
            f"PICKER_SATURATED: picker utilisation {picker_util:.0%} (capacity {sim_env.picker.capacity}); "
            "waiting is picker-limited. Check simulation.picker_capacity / picking_min semantics.")
            
    r1_amrs = [a for a in sim_env.amrs.values() if a.home_route == main]
    max_payload = max((a.payload_totes for a in r1_amrs), default=0.0)
    max_in_flight_totes = round(len(r1_amrs) * max_payload, 3)
    
    extra = {
        "condition_mode": condition_mode,
        "seed": seed,
        "sim_start": cond.sim_start.isoformat() if cond.sim_start else None,
        "applied_actions": plan.applied,
        "ignored_actions": plan.ignored,
        "reassignments": sim_env.reassign_log,
        "r1_queue_by_interval": metrics.queue_at_interval.get(main, []),
        "r1_demand_totes": round(sum(r.quantity_totes for r in r1_requests if not r.initial_backlog), 3),
        "r1_requests": len(r1_requests),
        "r1_backlog_end_totes": round(sim_env.backlog.get(main, 0.0), 3),
        "max_in_flight_totes": max_in_flight_totes,
        "priority_distribution": {0: sum(1 for r in r1_requests if r.priority == 0),
                                  1: sum(1 for r in r1_requests if r.priority == 1)},
        "delivered_by_route": {k: round(v, 3) for k, v in metrics.throughput_totes.items()},
        "trips_completed": dict(metrics.trips_completed),
        "buffer_end": {m: round(b.container.level, 3) for m, b in sim_env.line_buffers.items()},
        "buffer_min": {m: round(v, 3) for m, v in metrics.buffer_min_level.items()},
        "unmet_by_material": {k: round(v, 3) for k, v in metrics.unmet_by_material.items()},
        "starvation_events": [(m, round(s, 2), round(e, 2)) for m, s, e in metrics.starvation_events],
        "picker_utilization": round(picker_util, 4),
        "trip_log": metrics.trip_log,
        "warnings": cond.warnings,
        **r2,
    }

    return SimulationResult(
        scenario_id=scenario.scenario_id,
        avg_waiting_time=round(metrics.avg_wait(main, horizon), 4),
        max_waiting_time=round(metrics.max_wait(main, horizon), 4),
        avg_queue=round(metrics.avg_queue(main), 4),
        max_queue=round(metrics.max_queue(main), 4),
        late_delivery_count=metrics.late_count(main, horizon),
        throughput=round(metrics.throughput_totes.get(main, 0.0), 4),
        service_level=round(metrics.service_level(main, horizon), 4),
        starvation_minutes=round(metrics.starvation_minutes, 4),
        unmet_consumption=round(metrics.unmet_consumption, 4),
        buffer_overflow=round(metrics.buffer_overflow, 4),
        amr_utilization=amr_util,
        secondary_bottleneck=r2["r2_critical"],   # absolute; run_scenarios refines it relative to S0
        extra_metrics=extra,
    )


# ---------------------------------------------------------------------------
def run_scenarios(
    current_state: Any,
    future_condition: Any,
    scenarios: List[Scenario],
    seed: int = 42,
    condition_mode: Optional[str] = None,
    **kwargs: Any,
) -> List[SimulationResult]:
    """Run all scenarios with the SAME seed / future condition / data.

    Results are returned in the order of `scenarios`.  `secondary_bottleneck`
    is True only if R2 is critical here but was not critical in S0 (or got
    clearly worse than S0 when it already was).

    Raises ValueError if the list does not contain an S0 scenario
    (no-action baseline).
    """
    if kwargs.get("sys_cfg") is None or kwargs.get("thr_cfg") is None:
        kwargs["sys_cfg"], kwargs["thr_cfg"] = _load_configs()
    kwargs["sys_cfg"] = _compat_sys_cfg(kwargs["sys_cfg"])
    sys_cfg, thr_cfg = kwargs["sys_cfg"], kwargs["thr_cfg"]
    if isinstance(current_state, pd.DataFrame) and kwargs.get("current_df") is None:
        kwargs["current_df"] = current_state
    names = ("resource_df", "route_df", "station_df", "current_df", "material_df")
    if any(kwargs.get(n) is None for n in names):
        for n, df in zip(names, _load_master_data(sys_cfg)):
            if kwargs.get(n) is None:
                kwargs[n] = df
    thr = _thr(thr_cfg, sys_cfg)

    def one(sc: Scenario) -> SimulationResult:
        return run_simulation(current_state, future_condition, sc, seed=seed,
                              condition_mode=condition_mode, **kwargs)

    results = [one(sc) for sc in scenarios]
    base = next((r for sc, r in zip(scenarios, results) if sc.scenario_id == "S0"), None)
    if base is None:
        raise ValueError("scenarios must include the S0 baseline")

    b_crit = base.extra_metrics["r2_critical"]
    b_util = base.extra_metrics["r2_utilization"]
    b_wait = base.extra_metrics["r2_avg_wait"]
    for sc, r in zip(scenarios, results):
        crit, util = r.extra_metrics["r2_critical"], r.extra_metrics["r2_utilization"]
        wait = r.extra_metrics["r2_avg_wait"]
        worse = util > b_util + thr["worsen"] or wait > 1.1 * b_wait + 1.0
        r.extra_metrics["r2_critical_in_s0"] = b_crit
        r.secondary_bottleneck = bool(crit and (not b_crit or worse))
    return results


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Smoke run on the real package: future condition = history baseline + known events
    # (no forecast model needed).  Prints S0 vs a few what-if scenarios.
    def act(i, t, **p):
        return __import__("src.common.schemas", fromlist=["Action"]).Action(i, t, p)

    t0 = "2026-10-08 14:15:00"
    scs = [
        Scenario("S0", [], []),
        Scenario("S1", [act("A1", "REASSIGN_AMR", from_route="R2", to_route="R1", count=1, start_time=t0, duration_min=45)], ["AMR_AVAILABILITY_DROP"]),
        Scenario("S2", [act("A2", "CONSOLIDATE_DELIVERY", route="R1", start_time=t0, duration_min=45)], ["DEMAND_SPIKE"]),
        Scenario("S3", [act("A3", "PRIORITIZE_REQUEST", route="R1", start_time=t0, duration_min=45)], ["DEMAND_SPIKE"]),
        Scenario("S4", [act("A4", "ADJUST_REPLENISHMENT_TIME", route="R1", shift_min=5, start_time=t0, duration_min=45)], ["DEMAND_SPIKE"]),
        Scenario("S5", [act("A1", "REASSIGN_AMR", from_route="R2", to_route="R1", count=1, start_time=t0, duration_min=45),
                        act("A2", "CONSOLIDATE_DELIVERY", route="R1", start_time=t0, duration_min=45)], ["AMR_AVAILABILITY_DROP"]),
        Scenario("S6", [act("A6", "ALTERNATE_ROUTE", from_route="R1", to_route="R2", start_time=t0, duration_min=45)], ["TRAVEL_TIME_INCREASE"]),
    ]
    res = run_scenarios(None, None, scs, seed=42)
    print(f"{'id':3} {'wait':>6} {'maxW':>6} {'q_avg':>6} {'q_max':>6} {'late':>4} {'thru':>6} {'SL':>5} {'starv':>5} {'unmet':>6} {'ovf':>5} {'R2util':>6} {'sec':>5}")
    for r in res:
        e = r.extra_metrics
        print(f"{r.scenario_id:3} {r.avg_waiting_time:6.2f} {r.max_waiting_time:6.2f} {r.avg_queue:6.2f} {r.max_queue:6.2f} "
              f"{r.late_delivery_count:4d} {r.throughput:6.2f} {r.service_level:5.2f} {r.starvation_minutes:5.1f} "
              f"{r.unmet_consumption:6.2f} {r.buffer_overflow:5.2f} {e['r2_utilization']:6.2f} {str(r.secondary_bottleneck):>5}")
    print("ignored:", {r.scenario_id: r.extra_metrics["ignored_actions"] for r in res if r.extra_metrics["ignored_actions"]})
    print("warnings:", res[0].extra_metrics["warnings"])