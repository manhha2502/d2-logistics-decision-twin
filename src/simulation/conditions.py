"""
conditions.py — Turn "future condition" inputs into per-interval simulation inputs.

Accepted `future_condition` forms (all optional, may be mixed):
  * list[ForecastPoint]            (Dương)  -> R1 demand / process / travel P10-P50-P90
  * list[FutureState] / FutureState (Hà)    -> R2 demand, R1 amr_available
  * dict / object with any of the keys: forecasts, future_states, known_events,
    production_plan, sim_start

Expected = P50, Adverse = P90, Favorable = P10.  Known maintenance is applied
directly (never "guessed"): from known_future_events.csv (AMR id + window) or,
if no event file is available, derived from FutureState.amr_available.

Anything not provided is calibrated from *history* (never validation_only/):
mean demand per 15-min slot, mean job size and mean process times of the last
`baseline_lookback_days` days before sim_start.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

from src.common.schemas import ForecastPoint, FutureState

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Fallbacks used ONLY when neither forecast nor history provides a value.
# Override in config/system.yaml -> simulation:
DEFAULTS = {
    "default_picking_min": 3.0,
    "default_loading_min": 1.0,
    "default_unloading_min": 1.0,
    "baseline_lookback_days": 7,
    "calibrate_from_history": True,
    "arrival_jitter": True,
    "consumption_step_min": 1.0,
    "queue_sample_min": 1.0,
    "process_noise_cv": 0.0,
    "default_replenishment_shift_min": 5.0,
    "job_size_totes": None,       # None = calibrate from history, else payload
    "picker_capacity": None,      # None = station_master capacity
}

_DEFAULT_PATHS = {
    "known_events": "data/known_future/known_future_events.csv",
    "production_plan": "data/known_future/future_production_plan_15min.csv",
    "transport_jobs": "data/history/transport_jobs.csv",
    "trip_history": "data/history/process_trip_history_clean.csv",
}


import warnings

def sim_param(sys_cfg: dict, key: str) -> Any:
    sim = sys_cfg.get("simulation") or {}
    if key in sim:
        return sim[key]
    warnings.warn(f"Missing {key} in system.yaml under simulation: falling back to {DEFAULTS[key]}")
    return DEFAULTS[key]


# ---------------------------------------------------------------------------
@dataclass
class IntervalParams:
    demand: float
    picking: float
    loading: float
    unloading: float
    travel_loaded: float
    travel_empty: float


@dataclass
class MaintenanceWindow:
    amr_id: str
    start_min: float
    end_min: float


@dataclass
class FutureConditions:
    interval_min: float
    horizon_min: float
    sim_start: Optional[datetime]
    mode: str
    routes: dict[str, list[IntervalParams]]            # route -> params per interval
    consumption: dict[str, list[float]]                # material -> totes per interval
    demand_share: list[dict[str, float]]               # per interval material split of R1 demand
    maintenance: list[MaintenanceWindow] = field(default_factory=list)
    job_size: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def idx(self, t: float) -> int:
        n = len(next(iter(self.routes.values())))
        return max(0, min(int(t // self.interval_min), n - 1))

    def params(self, route: str, t: float) -> IntervalParams:
        return self.routes[route][self.idx(t)]

    def consumption_rate(self, material: str, t: float) -> float:
        series = self.consumption.get(material)
        if not series:
            return 0.0
        return series[min(self.idx(t), len(series) - 1)]

    def offset_min(self, ts: Any) -> Optional[float]:
        """Absolute timestamp -> minutes since sim_start (None if unknown)."""
        if self.sim_start is None:
            return None
        return (_to_dt(ts) - self.sim_start).total_seconds() / 60.0


# ---------------------------------------------------------------------------
def _to_dt(x: Any) -> datetime:
    if isinstance(x, datetime):
        return x
    return pd.Timestamp(x).to_pydatetime()


def _q(qv: Any, mode: str) -> float:
    if mode == "adverse":
        return float(qv.p90)
    if mode == "favorable":
        return float(qv.p10)
    return float(qv.p50)


def _read_csv(sys_cfg: dict, key: str) -> Optional[pd.DataFrame]:
    rel = (sys_cfg.get("paths") or {}).get(key, _DEFAULT_PATHS[key])
    path = Path(rel)
    if not path.is_absolute():
        path = _PROJECT_ROOT / rel
    if not path.exists():
        return None
    return pd.read_csv(path, encoding="utf-8-sig")


def _split_input(fc: Any) -> tuple[list, list, Any, Any, Any, Any]:
    forecasts: list = []
    states: list = []
    events = plan = start = None
    add_maint: Any = None      # int | list[str] | None
    if fc is None:
        return forecasts, states, events, plan, start, add_maint
    if isinstance(fc, dict):
        get = fc.get
    else:
        def get(k, d=None):
            return getattr(fc, k, d)
    if isinstance(fc, (list, tuple, ForecastPoint, FutureState)) or not (
        isinstance(fc, dict) or hasattr(fc, "forecasts") or hasattr(fc, "future_states")
    ):
        items = [fc] if isinstance(fc, (ForecastPoint, FutureState)) else list(fc)
    else:
        items = list(get("forecasts", None) or []) + list(get("future_states", None) or [])
        events, plan, start = get("known_events", None), get("production_plan", None), get("sim_start", None)
        add_maint = get("additional_amr_unavailable", None)
    for it in items:
        if isinstance(it, ForecastPoint):
            forecasts.append(it)
        elif isinstance(it, FutureState):
            states.append(it)
        else:
            raise TypeError(f"Unsupported future_condition item: {type(it).__name__}")
    forecasts.sort(key=lambda f: f.timestamp)
    states.sort(key=lambda s: s.timestamp)
    return forecasts, states, events, plan, start, add_maint


# ---------------------------------------------------------------------------
_CAL_CACHE: dict = {}


def calibrate_from_history(sys_cfg: dict, sim_start: Optional[datetime]) -> dict:
    """Baselines from history only (jobs + clean trips), strictly before sim_start."""
    lookback = int(sim_param(sys_cfg, "baseline_lookback_days"))
    key = (str(sys_cfg.get("paths")), sim_start, lookback)
    if key in _CAL_CACHE:
        return _CAL_CACHE[key]
    out: dict = {"demand_slot": {}, "demand_mean": {}, "job_size": {}, "times": {}}
    jobs = _read_csv(sys_cfg, "transport_jobs")
    if jobs is not None and not jobs.empty:
        jobs["issue_time"] = pd.to_datetime(jobs["issue_time"])
        if sim_start is not None:
            jobs = jobs[jobs["issue_time"] < sim_start]
        if not jobs.empty:
            jobs = jobs[jobs["issue_time"] >= jobs["issue_time"].max().normalize() - pd.Timedelta(days=lookback - 1)]
            jobs = jobs.assign(slot=jobs["issue_time"].dt.floor("15min"))
            for rid, g in jobs.groupby("route_id"):
                per_slot = g.groupby("slot")["quantity_totes"].sum()
                sod = per_slot.groupby(per_slot.index.hour * 4 + per_slot.index.minute // 15).mean()
                out["demand_slot"][rid] = sod.to_dict()
                out["demand_mean"][rid] = float(per_slot.mean())
                out["job_size"][rid] = float(g["quantity_totes"].mean())
    trips = _read_csv(sys_cfg, "trip_history")
    if trips is not None and not trips.empty:
        trips["start_time"] = pd.to_datetime(trips["start_time"])
        if sim_start is not None:
            trips = trips[trips["start_time"] < sim_start]
        if not trips.empty:
            trips = trips[trips["start_time"] >= trips["start_time"].max().normalize() - pd.Timedelta(days=lookback - 1)]
            for rid, g in trips.groupby("route_id"):
                out["times"][rid] = {
                    "loading": float(g["loading_min"].mean()),
                    "unloading": float(g["unloading_min"].mean()),
                    "travel_loaded": float(g["travel_loaded_min"].mean()),
                    "travel_empty": float(g["travel_empty_min"].mean()),
                }
    _CAL_CACHE[key] = out
    return out


# ---------------------------------------------------------------------------
def build_conditions(
    future_condition: Any,
    mode: str,
    sys_cfg: dict,
    route_df: pd.DataFrame,
    material_ids: list[str],
    amr_ids_by_route: dict[str, list[str]],
    known_events: Any = None,
    production_plan: Any = None,
    sim_start: Optional[datetime] = None,
    base_unavailable: Iterable[str] = (),
) -> FutureConditions:
    if mode not in ("expected", "adverse", "favorable"):
        raise ValueError(f"condition_mode must be expected/adverse/favorable, got {mode!r}")

    interval = float(sys_cfg["simulation"]["interval_min"])
    horizon = float(sys_cfg["simulation"]["horizon_min"])
    n = int(math.ceil(horizon / interval))
    main, aux = sys_cfg["routes"]["main"], sys_cfg["routes"]["auxiliary"]
    warnings: list[str] = []

    forecasts, states, ev_in, plan_in, start_in, add_maint = _split_input(future_condition)
    known_events = known_events if known_events is not None else ev_in
    production_plan = production_plan if production_plan is not None else plan_in

    # ---- time anchor -----------------------------------------------------
    if sim_start is None and start_in is not None:
        sim_start = _to_dt(start_in)
    if sim_start is None:
        first = forecasts[0].timestamp if forecasts else (states[0].timestamp if states else None)
        if first is not None:
            sim_start = _to_dt(first) - timedelta(minutes=interval)
    sim_start = _to_dt(sim_start) if sim_start is not None else None

    # ---- known events / plan ---------------------------------------------
    if known_events is None:
        known_events = _read_csv(sys_cfg, "known_events")
    events = _events_df(known_events)
    if production_plan is None:
        production_plan = _read_csv(sys_cfg, "production_plan")
    plan = _plan_df(production_plan)
    if sim_start is None and plan is not None:       # plan row 1 is the end of interval 1
        sim_start = plan["timestamp"].min().to_pydatetime() - timedelta(minutes=interval)

    cal = (
        calibrate_from_history(sys_cfg, sim_start)
        if sim_param(sys_cfg, "calibrate_from_history")
        else {"demand_slot": {}, "demand_mean": {}, "job_size": {}, "times": {}}
    )

    def interval_end(k: int) -> Optional[datetime]:
        return sim_start + timedelta(minutes=(k + 1) * interval) if sim_start else None

    def pick(seq: list, k: int, loc: Optional[str] = None):
        """Item whose timestamp == end of interval k, else positional, else last."""
        if loc is not None:
            seq = [s for s in seq if s.location == loc]
        if not seq:
            return None
        end = interval_end(k)
        if end is not None:
            for s in seq:
                if _to_dt(s.timestamp) == end:
                    return s
        return seq[min(k, len(seq) - 1)]

    def overlap_mult(route_or_target: str, etype: str, k: int) -> float:
        if events.empty or sim_start is None:
            return 1.0
        lo, hi = k * interval, (k + 1) * interval
        m = 1.0
        for _, e in events[(events["event_type"] == etype) & (events["target_id"] == route_or_target)].iterrows():
            s = (_to_dt(e["start_time"]) - sim_start).total_seconds() / 60.0
            f = (_to_dt(e["end_time"]) - sim_start).total_seconds() / 60.0
            frac = max(0.0, min(hi, f) - max(lo, s)) / interval
            m *= 1.0 + (float(e["magnitude"]) - 1.0) * frac
        return m

    # ---- per-route interval params ----------------------------------------
    r1_times = cal["times"].get(main, {})
    r2_times = cal["times"].get(aux, {})
    rt = {r["route_id"]: r for _, r in route_df.iterrows()}

    def base_time(route: str, name: str, route_col: Optional[str], default_key: Optional[str]) -> float:
        t = (cal["times"].get(route) or {}).get(name)
        if t is not None:
            return t
        if route_col and route in rt:
            return float(rt[route][route_col])
        return float(sim_param(sys_cfg, default_key))

    routes: dict[str, list[IntervalParams]] = {main: [], aux: []}
    demand_source = {main: set(), aux: set()}
    for k in range(n):
        slot = (sim_start + timedelta(minutes=k * interval)) if sim_start else None
        slot_key = (slot.hour * 4 + slot.minute // 15) if slot else None

        fp = pick(forecasts, k)
        fs1 = pick(states, k, main)
        fs2 = pick(states, k, aux)

        # R1 demand: forecast -> FutureState -> plan -> history baseline
        if fp is not None:
            d1 = _q(fp.demand, mode); demand_source[main].add("forecast")
        elif fs1 is not None:
            d1 = float(fs1.demand); demand_source[main].add("future_state")
        else:
            prow = _plan_row(plan, interval_end(k), k)
            if prow is not None:
                d1 = float(prow["planned_total_totes"]); demand_source[main].add("plan")
            elif main in cal["demand_slot"]:
                d1 = cal["demand_slot"][main].get(slot_key, cal["demand_mean"][main])
                d1 *= overlap_mult("LINE_A", "PRODUCTION_RAMP", k)
                demand_source[main].add("history")
            else:
                raise ValueError(
                    "No R1 demand source: pass ForecastPoint/FutureState, a production plan, "
                    "or enable history calibration (simulation.calibrate_from_history)."
                )

        # R2 demand: FutureState -> history baseline -> config -> 0 (warned)
        if fs2 is not None:
            d2 = float(fs2.demand); demand_source[aux].add("future_state")
        elif aux in cal["demand_slot"]:
            d2 = cal["demand_slot"][aux].get(slot_key, cal["demand_mean"][aux])
            d2 *= overlap_mult(aux, "AUX_ROUTE_PEAK", k)
            demand_source[aux].add("history")
        elif (sys_cfg.get("simulation") or {}).get("baseline_demand_r2") is not None:
            d2 = float(sys_cfg["simulation"]["baseline_demand_r2"])
            d2 *= overlap_mult(aux, "AUX_ROUTE_PEAK", k)
            demand_source[aux].add("config")
        else:
            d2 = 0.0
            if k == 0:
                warnings.append("No R2 demand baseline available: R2 simulated with zero demand.")

        def fv(attr: str, fallback: float) -> float:
            return _q(getattr(fp, attr), mode) if fp is not None else fallback

        pick_def = float(sim_param(sys_cfg, "default_picking_min"))
        p1 = fv("picking_time", pick_def)
        routes[main].append(IntervalParams(
            demand=max(0.0, d1),
            picking=p1,
            loading=fv("loading_time", base_time(main, "loading", None, "default_loading_min")),
            unloading=fv("unloading_time", base_time(main, "unloading", None, "default_unloading_min")),
            travel_loaded=fv("travel_loaded", base_time(main, "travel_loaded", "base_loaded_travel_min", None)),
            travel_empty=fv("travel_empty", base_time(main, "travel_empty", "base_empty_travel_min", None)),
        ))
        routes[aux].append(IntervalParams(
            demand=max(0.0, d2),
            picking=p1,   # shared picker station
            loading=base_time(aux, "loading", None, "default_loading_min"),
            unloading=base_time(aux, "unloading", None, "default_unloading_min"),
            travel_loaded=base_time(aux, "travel_loaded", "base_loaded_travel_min", None),
            travel_empty=base_time(aux, "travel_empty", "base_empty_travel_min", None),
        ))

    # other configured routes (e.g. a real alternate route): no own demand, own travel times
    for rid, row in rt.items():
        if rid in routes:
            continue
        routes[rid] = [IntervalParams(
            demand=0.0, picking=routes[main][k].picking,
            loading=base_time(rid, "loading", None, "default_loading_min"),
            unloading=base_time(rid, "unloading", None, "default_unloading_min"),
            travel_loaded=float(row["base_loaded_travel_min"]),
            travel_empty=float(row["base_empty_travel_min"])) for k in range(n)]

    # ---- consumption plan per material ------------------------------------
    consumption = {m: [] for m in material_ids}
    demand_share: list[dict[str, float]] = []
    for k in range(n):
        prow = _plan_row(plan, interval_end(k), k)
        d_mode = routes[main][k].demand
        if prow is not None:
            plan_m = {m: float(prow.get(f"planned_{m.lower()}_totes", 0.0) or 0.0) for m in material_ids}
            plan_tot = sum(plan_m.values())
            # scale consumption with the condition (P90 demand -> proportionally higher use)
            fp = pick(forecasts, k)
            scale = d_mode / _q(fp.demand, "expected") if fp is not None and _q(fp.demand, "expected") > 0 else 1.0
            cons = {m: plan_m[m] * scale for m in material_ids}
            share = {m: (plan_m[m] / plan_tot if plan_tot > 0 else 1.0 / len(material_ids)) for m in material_ids}
        else:
            share = {m: 1.0 / len(material_ids) for m in material_ids}
            cons = {m: d_mode * share[m] for m in material_ids}
            if k == 0:
                warnings.append("No production plan: consumption set equal to replenishment demand, split evenly.")
        for m in material_ids:
            consumption[m].append(cons[m])
        demand_share.append(share)

    # ---- maintenance windows ----------------------------------------------
    windows: list[MaintenanceWindow] = []
    if not events.empty and sim_start is not None:
        for _, e in events[events["event_type"] == "AMR_MAINTENANCE"].iterrows():
            s = (_to_dt(e["start_time"]) - sim_start).total_seconds() / 60.0
            f = (_to_dt(e["end_time"]) - sim_start).total_seconds() / 60.0
            if f > 0 and s < horizon:
                windows.append(MaintenanceWindow(str(e["target_id"]), max(0.0, s), min(horizon, f)))
    elif states:
        # No event file: derive from FutureState.amr_available (R1 only)
        ids = sorted(amr_ids_by_route.get(main, []))
        for k in range(n):
            fs = pick(states, k, main)
            if fs is None:
                continue
            lost = max(0, len(ids) - int(fs.amr_available))
            for amr_id in ids[len(ids) - lost:] if lost else []:
                windows.append(MaintenanceWindow(amr_id, k * interval, (k + 1) * interval))
    windows = _merge_windows(windows)

    # `additional_amr_unavailable` (adverse robustness) may arrive as:
    #   * int  -> remove N MORE R1 AMRs for the whole horizon.  AMRs that are already
    #             down (battery/current state, or known maintenance) are the LAST choice,
    #             so the extra loss is a real extra loss.  Never below 0 AMRs.
    #   * list -> explicit AMR ids;   * None/other -> nothing
    if isinstance(add_maint, bool):
        add_maint = None
    extra_ids: list[str] = []
    if isinstance(add_maint, int) and add_maint > 0:
        down = set(map(str, base_unavailable))

        def already_down_min(amr_id: str) -> float:
            return sum(w.end_min - w.start_min for w in windows if w.amr_id == amr_id)

        cands = [a for a in sorted(amr_ids_by_route.get(main, [])) if a not in down]
        cands.sort(key=lambda a: (already_down_min(a), [-ord(c) for c in a]))   # least-down first, then highest id
        extra_ids = cands[:add_maint]
    elif isinstance(add_maint, (list, tuple)):
        extra_ids = [str(a) for a in add_maint if a is not None]
    windows = _merge_windows(windows + [MaintenanceWindow(a, 0.0, horizon) for a in extra_ids])

    forced = sim_param(sys_cfg, "job_size_totes")
    job_size = {r: float(forced) if forced else cal["job_size"].get(r, 0.0) for r in (main, aux)}
    fc = FutureConditions(interval, horizon, sim_start, mode, routes, consumption,
                          demand_share, windows, job_size, warnings)
    fc.warnings.append("demand_source=" + ";".join(f"{r}:{'/'.join(sorted(s))}" for r, s in demand_source.items()))
    return fc


def _merge_windows(ws: list[MaintenanceWindow]) -> list[MaintenanceWindow]:
    out: list[MaintenanceWindow] = []
    for w in sorted(ws, key=lambda x: (x.amr_id, x.start_min)):
        if out and out[-1].amr_id == w.amr_id and w.start_min <= out[-1].end_min + 1e-9:
            out[-1].end_min = max(out[-1].end_min, w.end_min)
        else:
            out.append(MaintenanceWindow(w.amr_id, w.start_min, w.end_min))
    return out


def _events_df(x: Any) -> pd.DataFrame:
    cols = ["event_type", "target_id", "start_time", "end_time", "magnitude"]
    if x is None:
        return pd.DataFrame(columns=cols)
    df = x if isinstance(x, pd.DataFrame) else pd.DataFrame(list(x))
    return df if not df.empty else pd.DataFrame(columns=cols)


def _plan_df(x: Any) -> Optional[pd.DataFrame]:
    if x is None:
        return None
    df = x if isinstance(x, pd.DataFrame) else pd.DataFrame(list(x))
    if df.empty:
        return None
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


def _plan_row(plan: Optional[pd.DataFrame], end: Optional[datetime], k: int):
    if plan is None:
        return None
    if end is not None:
        m = plan[plan["timestamp"] == pd.Timestamp(end)]
        return m.iloc[0] if not m.empty else None
    return plan.iloc[k] if k < len(plan) else None