"""
test_simulation.py — tests for Phú's SimPy What-if Digital Twin.

Hermetic: master data, config, forecasts, events are injected; no CSV is read
(except the single `real_data` smoke test at the bottom).

The 8 mandatory tests of D2_IMPLEMENTATION_PLAN.md are tests 1-8 (the old
versions passed vacuously: demand was 0, so R1 never ran — see test_r1_really_runs).
"""
import copy
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.schemas import Action, ForecastPoint, FutureState, QuantileValue, Scenario
from src.simulation.simulator import run_scenarios, run_simulation

NOW = datetime(2026, 10, 8, 14, 0, 0)
T15 = "2026-10-08 14:15:00"
EMPTY_EVENTS = pd.DataFrame(columns=["event_type", "target_id", "start_time", "end_time", "magnitude"])
EMPTY_PLAN = pd.DataFrame()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def cfg():
    sys_cfg = {
        "simulation": {
            "horizon_min": 60, "interval_min": 15, "default_seed": 42,
            "calibrate_from_history": False,
            "job_size_totes": 1.5,
            "picker_capacity": 2,
            "baseline_demand_r2": 2.0,
            "arrival_jitter": True,
            "default_picking_min": 3.0,
            "default_loading_min": 1.0,
            "default_unloading_min": 1.0,
            "process_noise_cv": 0.0,
            "consumption_step_min": 1.0,
            "queue_sample_min": 1.0,
        },
        "paths": {},
        "routes": {"main": "R1", "auxiliary": "R2", "line_buffer_station": "LINE_A_BUF",
                   "picker_station": "PICK", "staging_r1": "STG_R1"},
        "secondary_bottleneck": {"utilization_threshold": 0.80, "adverse_reduce_amr": False},
    }
    thr_cfg = {"simulation": {"late_delivery_threshold_min": 20.0,
                              "secondary_bottleneck_utilization": 0.80,
                              "min_dispatch_battery_pct": 20.0}}
    return sys_cfg, thr_cfg


@pytest.fixture
def dfs():
    amr = [("AMR01", "R1"), ("AMR02", "R1"), ("AMR03", "R1"), ("AMR04", "R2"), ("AMR05", "R2")]
    resource = pd.DataFrame([{"resource_id": a, "resource_type": "AMR", "home_route": r, "payload_totes": 3} for a, r in amr])
    route = pd.DataFrame([
        {"route_id": "R1", "origin": "Warehouse", "destination": "LINE_A", "distance_m": 520,
         "base_loaded_travel_min": 5.2, "base_empty_travel_min": 4.3, "staging_capacity_totes": 24},
        {"route_id": "R2", "origin": "Warehouse", "destination": "AUX_AREA", "distance_m": 410,
         "base_loaded_travel_min": 4.5, "base_empty_travel_min": 3.8, "staging_capacity_totes": 16},
    ])
    station = pd.DataFrame([
        {"station_id": "PICK", "station_type": "Picking", "capacity": 1},
        {"station_id": "STG_R1", "station_type": "Staging", "capacity": 24},
        {"station_id": "LINE_A_BUF", "station_type": "Line-side Buffer", "capacity": 52},
    ])
    rows = []
    for a, _ in amr:
        rows += [{"entity_type": "RESOURCE", "entity_id": a, "metric": "battery_pct", "value": 100},
                 {"entity_type": "RESOURCE", "entity_id": a, "metric": "available", "value": 1}]
    rows += [{"entity_type": "BUFFER", "entity_id": "MAT_A", "metric": "current_level_totes", "value": 20},
             {"entity_type": "BUFFER", "entity_id": "MAT_B", "metric": "current_level_totes", "value": 15}]
    current = pd.DataFrame(rows)
    material = pd.DataFrame([{"material_id": "MAT_A", "buffer_capacity_totes": 28},
                             {"material_id": "MAT_B", "buffer_capacity_totes": 24}])
    return resource, route, station, current, material


def fp(demand=6.0, spread=0.25, n=4):
    """list[ForecastPoint] +15..+60; P10/P50/P90 around the given P50 demand."""
    def qv(x, s):
        return QuantileValue(x * (1 - s), x, x * (1 + s))
    return [ForecastPoint(
        timestamp=NOW + timedelta(minutes=15 * (k + 1)),
        demand=qv(demand, spread), travel_loaded=qv(5.5, 0.2), travel_empty=qv(4.5, 0.2),
        picking_time=qv(2.0, 0.2), loading_time=qv(1.0, 0.1), unloading_time=qv(1.0, 0.1),
    ) for k in range(n)]


def act(aid, typ, **params):
    return Action(aid, typ, params)


S0 = Scenario("S0", [], [])


def run(scn=S0, cfg=None, dfs=None, fc="default", mode=None, seed=42, events=EMPTY_EVENTS,
        plan=EMPTY_PLAN, current=None, resource=None, sys_over=None, thr_over=None):
    sys_cfg, thr_cfg = copy.deepcopy(cfg)
    if sys_over:
        sys_cfg["simulation"].update(sys_over)
    if thr_over:
        thr_cfg["simulation"].update(thr_over)
    resource_df, route_df, station_df, current_df, material_df = dfs
    return run_simulation(
        None, fp() if fc == "default" else fc, scn, seed=seed, condition_mode=mode,
        sys_cfg=sys_cfg, thr_cfg=thr_cfg,
        resource_df=resource if resource is not None else resource_df,
        route_df=route_df, station_df=station_df,
        current_df=current if current is not None else current_df,
        material_df=material_df, known_events=events, production_plan=plan)


def maint(amr, start, end):
    return pd.DataFrame([{"event_type": "AMR_MAINTENANCE", "target_id": amr, "start_time": start,
                          "end_time": end, "magnitude": 1.0}])


# ---------------------------------------------------------------------------
# Mandatory 1 — same input + same seed -> same result
# ---------------------------------------------------------------------------
def test_same_seed_reproducible(cfg, dfs):
    a, b = run(cfg=cfg, dfs=dfs, seed=7), run(cfg=cfg, dfs=dfs, seed=7)
    assert a == b                                   # every KPI AND extra_metrics (incl. trip log)


def test_seed_is_used_but_global_rng_untouched(cfg, dfs):
    random.seed(123); np.random.seed(123)
    r_py, r_np = random.random(), np.random.rand()
    random.seed(123); np.random.seed(123)
    a = run(cfg=cfg, dfs=dfs, seed=1)
    run(cfg=cfg, dfs=dfs, seed=2)
    assert (random.random(), np.random.rand()) == (r_py, r_np)   # no global RNG state consumed
    assert a.extra_metrics["trip_log"] != run(cfg=cfg, dfs=dfs, seed=2).extra_metrics["trip_log"]


# ---------------------------------------------------------------------------
# Mandatory 2 — S0 runs, and R1 really runs (old tests passed with R1 never simulated)
# ---------------------------------------------------------------------------
def test_s0_runs_and_result_is_valid(cfg, dfs):
    r = run(cfg=cfg, dfs=dfs)
    assert r.scenario_id == "S0"
    assert 0.0 <= r.service_level <= 1.0
    assert r.throughput > 0 and r.avg_queue >= 0 and r.max_queue >= r.avg_queue
    assert r.max_waiting_time >= r.avg_waiting_time >= 0
    assert set(r.amr_utilization) == {"AMR01", "AMR02", "AMR03", "AMR04", "AMR05"}
    assert all(0.0 <= u <= 1.0 for u in r.amr_utilization.values())
    assert r.secondary_bottleneck is False


def test_r1_really_runs(cfg, dfs):
    r = run(cfg=cfg, dfs=dfs)
    assert r.extra_metrics["trips_completed"]["R1"] > 0
    assert any(r.amr_utilization[a] > 0 for a in ("AMR01", "AMR02", "AMR03"))
    d = r.extra_metrics["r1_demand_totes"]
    assert d == pytest.approx(6.0 * 4, rel=1e-6)    # 4 intervals x P50 demand


def test_no_demand_source_is_an_error_not_silent_zero(cfg, dfs):
    with pytest.raises(ValueError, match="No R1 demand source"):
        run(cfg=cfg, dfs=dfs, fc=None)


# ---------------------------------------------------------------------------
# Mandatory 3 — remove 1 AMR -> waiting must not get better
# ---------------------------------------------------------------------------
def test_remove_amr_does_not_improve_waiting(cfg, dfs):
    heavy = fp(demand=9.0)
    base = run(cfg=cfg, dfs=dfs, fc=heavy)
    cur = dfs[3].copy()
    cur.loc[(cur.entity_id == "AMR03") & (cur.metric == "battery_pct"), "value"] = 5.0   # < min dispatch
    deg = run(cfg=cfg, dfs=dfs, fc=heavy, current=cur)
    assert deg.amr_utilization["AMR03"] == 0.0
    assert deg.avg_waiting_time > base.avg_waiting_time          # strictly worse at this load
    assert deg.throughput <= base.throughput
    assert deg.avg_queue >= base.avg_queue


# ---------------------------------------------------------------------------
# Mandatory 4 — add capacity -> throughput must not drop
# ---------------------------------------------------------------------------
def test_add_capacity_does_not_decrease_throughput(cfg, dfs):
    heavy = fp(demand=9.0)
    base = run(cfg=cfg, dfs=dfs, fc=heavy)
    resource, _, _, current, _ = dfs
    res2 = pd.concat([resource, pd.DataFrame([{"resource_id": "AMR06", "resource_type": "AMR",
                                               "home_route": "R1", "payload_totes": 3}])], ignore_index=True)
    cur2 = pd.concat([current, pd.DataFrame([
        {"entity_type": "RESOURCE", "entity_id": "AMR06", "metric": "battery_pct", "value": 100},
        {"entity_type": "RESOURCE", "entity_id": "AMR06", "metric": "available", "value": 1}])], ignore_index=True)
    more = run(cfg=cfg, dfs=dfs, fc=heavy, resource=res2, current=cur2)
    assert more.throughput >= base.throughput
    assert more.avg_waiting_time <= base.avg_waiting_time


# ---------------------------------------------------------------------------
# Mandatory 5 — buffer never negative / above capacity; starvation tracked
# ---------------------------------------------------------------------------
def test_buffer_within_bounds(cfg, dfs):
    r = run(cfg=cfg, dfs=dfs, fc=fp(demand=12.0))
    caps = {"MAT_A": 28, "MAT_B": 24}
    for m, lvl in r.extra_metrics["buffer_end"].items():
        assert 0.0 <= lvl <= caps[m] + 1e-9
    assert all(v >= 0.0 for v in r.extra_metrics["buffer_min"].values())
    assert r.unmet_consumption >= 0 and r.buffer_overflow >= 0


def test_starvation_is_tracked_when_buffer_runs_dry(cfg, dfs):
    cur = dfs[3].copy()
    cur.loc[cur.metric == "current_level_totes", "value"] = 1.0
    r = run(cfg=cfg, dfs=dfs, current=cur, fc=fp(demand=6.0),
            events=maint("AMR01", T15.replace("14:15", "14:00"), "2026-10-08 15:00:00"),
            sys_over={"picker_capacity": 2})
    assert r.starvation_minutes > 0
    assert r.unmet_consumption > 0
    assert min(r.extra_metrics["buffer_min"].values()) == 0.0
    ev = r.extra_metrics["starvation_events"]
    assert ev and all(end >= start for _, start, end in ev)       # start/end recorded


def test_overflow_when_buffer_is_full(cfg, dfs):
    cur = dfs[3].copy()
    cur.loc[cur.metric == "current_level_totes", "value"] = 100.0     # clamped to capacity
    plan = pd.DataFrame([{"timestamp": NOW + timedelta(minutes=15 * (k + 1)),
                          "planned_mat_a_totes": 0.01, "planned_mat_b_totes": 0.01,
                          "planned_total_totes": 0.02} for k in range(4)])
    r = run(cfg=cfg, dfs=dfs, current=cur, plan=plan)
    assert r.buffer_overflow > 0
    assert r.extra_metrics["buffer_end"]["MAT_A"] <= 28 + 1e-9


# ---------------------------------------------------------------------------
# Mandatory 6 — maintenance AMR must not be used
# ---------------------------------------------------------------------------
def test_unavailable_amr_not_used(cfg, dfs):
    cur = dfs[3].copy()
    cur.loc[(cur.entity_id == "AMR01") & (cur.metric == "available"), "value"] = 0
    r = run(cfg=cfg, dfs=dfs, current=cur)
    assert r.amr_utilization["AMR01"] == 0.0
    assert all(t[0] != "AMR01" for t in r.extra_metrics["trip_log"])


def test_known_maintenance_window_is_respected(cfg, dfs):
    ev = maint("AMR03", "2026-10-08 14:15:00", "2026-10-08 15:00:00")      # offsets 15..60
    r = run(cfg=cfg, dfs=dfs, fc=fp(demand=9.0), events=ev)
    log = [t for t in r.extra_metrics["trip_log"] if t[0] == "AMR03"]
    assert log, "AMR03 should work before its maintenance starts"
    assert all(start < 15.0 for _, _, start, _, _ in log)                  # never dispatched inside window
    base = run(cfg=cfg, dfs=dfs, fc=fp(demand=9.0))
    assert r.throughput < base.throughput                                  # maintenance really costs capacity


# ---------------------------------------------------------------------------
# Mandatory 7 — reassigning R2 -> R1 can cause an R2 secondary bottleneck
# ---------------------------------------------------------------------------
REASSIGN = act("A1", "REASSIGN_AMR", from_route="R2", to_route="R1", count=1)


def test_reassign_amr_triggers_secondary_bottleneck(cfg, dfs):
    s1 = Scenario("S1", [REASSIGN], ["AMR_AVAILABILITY_DROP"])
    heavy_r2 = {"baseline_demand_r2": 3.0}
    base = run(cfg=cfg, dfs=dfs, sys_over=heavy_r2)
    res = run(s1, cfg=cfg, dfs=dfs, sys_over=heavy_r2)
    assert res.extra_metrics["r2_utilization"] > base.extra_metrics["r2_utilization"]
    assert res.extra_metrics["r2_critical"] is True


def test_secondary_bottleneck_via_run_scenarios_is_relative_to_s0(cfg, dfs):
    sys_cfg, thr_cfg = copy.deepcopy(cfg)
    sys_cfg["simulation"]["baseline_demand_r2"] = 3.0
    s1 = Scenario("S1", [REASSIGN], [])
    kw = dict(sys_cfg=sys_cfg, thr_cfg=thr_cfg, resource_df=dfs[0], route_df=dfs[1], station_df=dfs[2],
              current_df=dfs[3], material_df=dfs[4], known_events=EMPTY_EVENTS, production_plan=EMPTY_PLAN)
    out = run_scenarios(None, fp(), [S0, s1], seed=42, **kw)
    assert [r.scenario_id for r in out] == ["S0", "S1"]
    assert out[1].secondary_bottleneck is True
    assert out[0].secondary_bottleneck is False                # S0 never "became" a secondary bottleneck


def test_reassign_amr_does_not_flag_when_r2_has_slack(cfg, dfs):
    res = run(Scenario("S1", [REASSIGN], []), cfg=cfg, dfs=dfs, sys_over={"baseline_demand_r2": 1.0})   # 1 AMR is enough
    assert res.secondary_bottleneck is False


# ---------------------------------------------------------------------------
# Mandatory 8 — actions really change the simulation
# ---------------------------------------------------------------------------
def test_reassign_amr_changes_simulation_and_helps_r1(cfg, dfs):
    heavy = fp(demand=10.0)
    base = run(cfg=cfg, dfs=dfs, fc=heavy)
    res = run(Scenario("S1", [REASSIGN], []), cfg=cfg, dfs=dfs, fc=heavy)
    assert res.extra_metrics["reassignments"][0]["amrs"] == ["AMR04"]
    assert any(t[0] == "AMR04" and t[1] == "R1" for t in res.extra_metrics["trip_log"])   # R2 AMR now serves R1
    assert res.throughput > base.throughput
    assert res.avg_waiting_time < base.avg_waiting_time
    assert res.amr_utilization != base.amr_utilization


def test_reassign_is_applied_immediately_not_after_old_route_request(cfg, dfs):
    """Regression: the old AMR loop stayed blocked on the old route's Store after reassign."""
    res = run(Scenario("S1", [REASSIGN], []), cfg=cfg, dfs=dfs, fc=fp(demand=10.0), sys_over={"baseline_demand_r2": 0.0})
    first_r1 = min(t[2] for t in res.extra_metrics["trip_log"] if t[0] == "AMR04" and t[1] == "R1")
    assert first_r1 < 15.0


def test_reassign_respects_start_time_and_duration(cfg, dfs):
    a = act("A1", "REASSIGN_AMR", from_route="R2", to_route="R1", count=1,
            start_time="2026-10-08 14:15:00", duration_min=15)
    res = run(Scenario("S1", [a], []), cfg=cfg, dfs=dfs, fc=fp(demand=16.0), sys_over={"baseline_demand_r2": 1.0})
    log = res.extra_metrics["reassignments"][0]
    assert (log["t"], log["reverted_at"]) == (15.0, 30.0)
    moved = log["amrs"][0]                                             # idle R2 AMR is chosen first
    r1_trips = [t for t in res.extra_metrics["trip_log"] if t[0] == moved and t[1] == "R1"]
    assert r1_trips
    assert all(start >= 15.0 for _, _, start, _, _ in r1_trips)
    assert all(start < 30.0 for _, _, start, _, _ in r1_trips)         # back on R2 after 15 min


def test_consolidate_delivery_carries_more_per_trip(cfg, dfs):
    heavy = fp(demand=10.0)
    base = run(cfg=cfg, dfs=dfs, fc=heavy)
    res = run(Scenario("S2", [act("A2", "CONSOLIDATE_DELIVERY", route="R1")], []), cfg=cfg, dfs=dfs, fc=heavy)
    avg = lambda r: np.mean([t[4] for t in r.extra_metrics["trip_log"] if t[1] == "R1"])
    assert avg(res) > avg(base) + 0.2
    assert max(t[4] for t in res.extra_metrics["trip_log"]) <= 3.0 + 1e-9      # never above AMR payload
    assert res.throughput > base.throughput
    assert res.avg_waiting_time < base.avg_waiting_time


def test_prioritize_request_reorders_shared_picker(cfg, dfs):
    tight = {"picker_capacity": 1, "baseline_demand_r2": 6.0}
    base = run(cfg=cfg, dfs=dfs, fc=fp(demand=8.0), sys_over=tight)
    res = run(Scenario("S3", [act("A3", "PRIORITIZE_REQUEST", route="R1")], []), cfg=cfg, dfs=dfs,
              fc=fp(demand=8.0), sys_over=tight)
    assert res.avg_waiting_time < base.avg_waiting_time                # R1 jumps the picker queue
    assert res.extra_metrics["r2_avg_wait"] > base.extra_metrics["r2_avg_wait"]   # ... at R2's expense


def test_adjust_replenishment_time_releases_earlier(cfg, dfs):
    heavy = fp(demand=9.0)
    base = run(cfg=cfg, dfs=dfs, fc=heavy)
    res = run(Scenario("S4", [act("A4", "ADJUST_REPLENISHMENT_TIME", route="R1", shift_min=6)], []),
              cfg=cfg, dfs=dfs, fc=heavy)
    assert res.avg_waiting_time < base.avg_waiting_time                # measured from NEED time
    assert res.service_level >= base.service_level
    assert res.extra_metrics["r1_demand_totes"] == base.extra_metrics["r1_demand_totes"]


def test_alternate_route_is_ignored_without_a_real_alternative(cfg, dfs):
    a = act("A6", "ALTERNATE_ROUTE", from_route="R1", to_route="R2")       # R2 -> AUX_AREA, not LINE_A
    res = run(Scenario("S6", [a], []), cfg=cfg, dfs=dfs)
    base = run(cfg=cfg, dfs=dfs)
    assert res.extra_metrics["ignored_actions"][0]["reason"] == "NO_ALTERNATIVE_ROUTE_CONFIGURED"
    assert res.extra_metrics["trip_log"] == base.extra_metrics["trip_log"]  # R2 never became an alternate route


def test_alternate_route_works_only_if_route_exists_with_same_destination(cfg, dfs):
    resource, route, station, current, material = dfs
    route2 = pd.concat([route, pd.DataFrame([{"route_id": "R3", "origin": "Warehouse", "destination": "LINE_A",
                                               "distance_m": 600, "base_loaded_travel_min": 6.0,
                                               "base_empty_travel_min": 5.0, "staging_capacity_totes": 12}])],
                       ignore_index=True)
    a = act("A6", "ALTERNATE_ROUTE", from_route="R1", to_route="R3")
    sys_cfg, thr_cfg = copy.deepcopy(cfg)
    res = run_simulation(None, fp(), Scenario("S6", [a], []), seed=42, sys_cfg=sys_cfg, thr_cfg=thr_cfg,
                         resource_df=resource, route_df=route2, station_df=station, current_df=current,
                         material_df=material, known_events=EMPTY_EVENTS, production_plan=EMPTY_PLAN)
    assert res.extra_metrics["applied_actions"] == ["A6"]
    assert not res.extra_metrics["ignored_actions"]


def test_unknown_action_and_late_start_are_reported_not_crashing(cfg, dfs):
    late = act("A7", "PRIORITIZE_REQUEST", route="R1", start_time="2026-10-08 16:00:00")
    res = run(Scenario("SX", [act("A8", "TELEPORT"), late], []), cfg=cfg, dfs=dfs)
    reasons = {i["reason"] for i in res.extra_metrics["ignored_actions"]}
    assert reasons == {"UNKNOWN_ACTION_TYPE", "STARTS_AFTER_HORIZON"}


# ---------------------------------------------------------------------------
# Scenario comparison fairness
# ---------------------------------------------------------------------------
def test_run_scenarios_uses_identical_arrivals_for_s0_and_scenarios(cfg, dfs):
    sys_cfg, thr_cfg = copy.deepcopy(cfg)
    kw = dict(sys_cfg=sys_cfg, thr_cfg=thr_cfg, resource_df=dfs[0], route_df=dfs[1], station_df=dfs[2],
              current_df=dfs[3], material_df=dfs[4], known_events=EMPTY_EVENTS, production_plan=EMPTY_PLAN)
    scs = [S0, Scenario("S1", [REASSIGN], []), Scenario("S2", [act("A2", "CONSOLIDATE_DELIVERY", route="R1")], [])]
    out = run_scenarios(None, fp(9.0), scs, seed=3, **kw)
    standalone = run(S0, cfg=cfg, dfs=dfs, fc=fp(9.0), seed=3)
    assert out[0].extra_metrics["trip_log"] == standalone.extra_metrics["trip_log"]
    assert len({r.extra_metrics["r1_demand_totes"] for r in out}) == 1          # same demand everywhere
    assert len({r.extra_metrics["r1_requests"] for r in out}) == 1


# ---------------------------------------------------------------------------
# Future conditions: P10/P50/P90, FutureState, regression for queue/service level
# ---------------------------------------------------------------------------
def test_condition_modes_order_p10_p50_p90(cfg, dfs):
    heavy = fp(demand=8.0, spread=0.3)
    fav, exp, adv = (run(cfg=cfg, dfs=dfs, fc=heavy, mode=m) for m in ("favorable", "expected", "adverse"))
    assert fav.extra_metrics["r1_demand_totes"] < exp.extra_metrics["r1_demand_totes"] < adv.extra_metrics["r1_demand_totes"]
    assert fav.avg_waiting_time <= exp.avg_waiting_time <= adv.avg_waiting_time


def test_adverse_can_remove_one_more_amr_from_config_never_below_zero(cfg, dfs):
    base = run(cfg=cfg, dfs=dfs, fc=fp(9.0), mode="adverse")
    reduced = run(cfg=cfg, dfs=dfs, fc=fp(9.0), mode="adverse")
    sys_cfg, thr_cfg = copy.deepcopy(cfg)
    sys_cfg["secondary_bottleneck"]["adverse_reduce_amr"] = True
    flagged = run_simulation(None, fp(9.0), S0, seed=42, condition_mode="adverse", sys_cfg=sys_cfg, thr_cfg=thr_cfg,
                             resource_df=dfs[0], route_df=dfs[1], station_df=dfs[2], current_df=dfs[3],
                             material_df=dfs[4], known_events=EMPTY_EVENTS, production_plan=EMPTY_PLAN)
    assert flagged.throughput <= reduced.throughput == base.throughput
    assert flagged.avg_waiting_time >= reduced.avg_waiting_time


def test_future_state_list_is_accepted_and_amr_drop_reduces_capacity(cfg, dfs):
    def fs(loc, k, demand, amr):
        return FutureState(NOW + timedelta(minutes=15 * (k + 1)), loc, demand, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, amr)
    ok = [fs("R1", k, 9.0, 3) for k in range(4)] + [fs("R2", k, 2.0, 2) for k in range(4)]
    drop = [fs("R1", k, 9.0, 2 if k >= 1 else 3) for k in range(4)] + [fs("R2", k, 2.0, 2) for k in range(4)]
    a = run(cfg=cfg, dfs=dfs, fc=ok)
    b = run(cfg=cfg, dfs=dfs, fc=drop)
    assert a.extra_metrics["r1_demand_totes"] == pytest.approx(36.0)
    assert b.throughput < a.throughput
    assert b.avg_waiting_time > a.avg_waiting_time


def test_dict_future_condition_with_known_events(cfg, dfs):
    fc = {"forecasts": fp(9.0), "known_events": maint("AMR03", "2026-10-08 14:15:00", "2026-10-08 15:00:00")}
    r = run(cfg=cfg, dfs=dfs, fc=fc, events=None)
    assert all(t[2] < 15.0 for t in r.extra_metrics["trip_log"] if t[0] == "AMR03")


def test_queue_is_sampled_over_time_even_when_nothing_is_served(cfg, dfs):
    """Regression: queue used to be sampled only when an AMR picked a request -> 0 when no AMR worked."""
    ev = pd.concat([maint(a, "2026-10-08 14:00:00", "2026-10-08 15:00:00") for a in ("AMR01", "AMR02", "AMR03")])
    r = run(cfg=cfg, dfs=dfs, events=ev)
    assert r.throughput == 0
    assert r.avg_queue > 0 and r.max_queue > r.avg_queue
    q = r.extra_metrics["r1_queue_by_interval"]
    assert len(q) == 4 and q == sorted(q) and q[-1] > q[0]
    assert r.service_level < 1.0                      # unserved requests are censored, not ignored
    assert r.late_delivery_count > 0


def test_totes_are_conserved(cfg, dfs):
    r = run(cfg=cfg, dfs=dfs, fc=fp(9.0))
    e = r.extra_metrics
    in_flight = e["r1_demand_totes"] - e["delivered_by_route"].get("R1", 0.0) - e["r1_backlog_end_totes"] - r.buffer_overflow
    assert in_flight >= -1e-6                         # nothing delivered that was never demanded
    assert in_flight <= e["max_in_flight_totes"] + 1e-6                  # dynamic max in-flight


# ---------------------------------------------------------------------------
# Real data smoke (skipped if the CSV package is not present)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / "data/master/route_master.csv").exists(), reason="data package missing")
def test_real_data_smoke_history_baseline_and_known_events():
    scs = [S0, Scenario("S1", [act("A1", "REASSIGN_AMR", from_route="R2", to_route="R1", count=1,
                                    start_time=T15, duration_min=45)], [])]
    out = run_scenarios(None, None, scs, seed=42)
    s0, s1 = out
    assert s0.throughput > 0 and s0.extra_metrics["trips_completed"]["R1"] > 0
    assert all(t[2] < 15.0 for t in s0.extra_metrics["trip_log"] if t[0] == "AMR03")                  # EV028 window
    assert s1.throughput > s0.throughput
    assert out == run_scenarios(None, None, scs, seed=42)                                               # reproducible


# ---------------------------------------------------------------------------
# Regression: additional_amr_unavailable may be int or list
# ---------------------------------------------------------------------------
def test_additional_amr_unavailable_accepts_int(cfg, dfs):
    """Hạ may send `additional_amr_unavailable` as int (README example uses 0)."""
    fc = {
        "forecasts": fp(9.0),
        "known_events": EMPTY_EVENTS,
        "production_plan": EMPTY_PLAN,
        "additional_amr_unavailable": 1,   # int
    }
    res = run(cfg=cfg, dfs=dfs, fc=fc)
    # Exactly one R1 AMR removed for whole horizon -> throughput drops
    base = run(cfg=cfg, dfs=dfs, fc=fp(9.0))
    assert res.throughput < base.throughput


def test_additional_amr_unavailable_accepts_list(cfg, dfs):
    """Caller may send explicit AMR ids as list."""
    fc = {
        "forecasts": fp(9.0),
        "known_events": EMPTY_EVENTS,
        "production_plan": EMPTY_PLAN,
        "additional_amr_unavailable": ["AMR03"],
    }
    res = run(cfg=cfg, dfs=dfs, fc=fc)
    assert res.amr_utilization["AMR03"] == 0.0


def test_additional_amr_unavailable_accepts_none(cfg, dfs):
    """Default None must not crash or change behaviour vs no key at all."""
    fc_with = {"forecasts": fp(9.0), "additional_amr_unavailable": None}
    fc_without = {"forecasts": fp(9.0)}
    a = run(cfg=cfg, dfs=dfs, fc=fc_with)
    b = run(cfg=cfg, dfs=dfs, fc=fc_without)
    assert a.throughput == b.throughput


# ---------------------------------------------------------------------------
# Regression: alias params must not trigger UNKNOWN_PARAMS warning
# ---------------------------------------------------------------------------
def test_param_alias_does_not_trigger_unknown_params_warning(cfg, dfs):
    """Passing both `route` and `target_line` (alias) must not warn."""
    a = act("A1", "PRIORITIZE_REQUEST", route="R1", target_line="LINE_A")
    res = run(Scenario("S1", [a], []), cfg=cfg, dfs=dfs)
    warnings = res.extra_metrics["warnings"]
    unknown = [w for w in warnings if "UNKNOWN_PARAMS" in w]
    assert unknown == [], f"Alias param triggered spurious warning: {unknown}"


def test_true_unknown_param_does_trigger_warning(cfg, dfs):
    """A genuinely unused param must still be flagged."""
    a = act("A1", "PRIORITIZE_REQUEST", route="R1", something_typo="x")
    res = run(Scenario("S1", [a], []), cfg=cfg, dfs=dfs)
    warnings = res.extra_metrics["warnings"]
    unknown = [w for w in warnings if "UNKNOWN_PARAMS" in w and "something_typo" in w]
    assert unknown, "Genuinely unknown param was not flagged"


# ---------------------------------------------------------------------------
# Regression: Hạ's pipeline contract (condition / quantile keys, secondary flag)
# ---------------------------------------------------------------------------
def _pipeline_dict(condition, quantile, **extra):
    return {"condition": condition, "quantile": quantile, "forecasts": fp(8.0, spread=0.3),
            "known_events": EMPTY_EVENTS, "production_plan": EMPTY_PLAN, **extra}


def test_condition_key_in_dict_selects_quantile(cfg, dfs):
    """Pipeline sends condition/quantile inside future_condition and NO condition_mode kwarg."""
    fav = run(cfg=cfg, dfs=dfs, fc=_pipeline_dict("favorable", "p10"), events=None, plan=None)
    exp = run(cfg=cfg, dfs=dfs, fc=_pipeline_dict("expected", "p50"), events=None, plan=None)
    adv = run(cfg=cfg, dfs=dfs, fc=_pipeline_dict("adverse", "p90"), events=None, plan=None)
    assert (fav.extra_metrics["condition_mode"], exp.extra_metrics["condition_mode"],
            adv.extra_metrics["condition_mode"]) == ("favorable", "expected", "adverse")
    assert fav.extra_metrics["r1_demand_totes"] < exp.extra_metrics["r1_demand_totes"] < adv.extra_metrics["r1_demand_totes"]
    assert fav.avg_waiting_time <= exp.avg_waiting_time <= adv.avg_waiting_time


def test_quantile_alone_is_enough_and_conflicts_are_errors(cfg, dfs):
    q_only = {"quantile": "p90", "forecasts": fp(8.0, spread=0.3)}
    assert run(cfg=cfg, dfs=dfs, fc=q_only).extra_metrics["condition_mode"] == "adverse"
    with pytest.raises(ValueError, match="Conflicting"):
        run(cfg=cfg, dfs=dfs, fc=_pipeline_dict("adverse", "p50"), events=None, plan=None)
    with pytest.raises(ValueError, match="quantile"):
        run(cfg=cfg, dfs=dfs, fc={"quantile": "p99", "forecasts": fp()})


def test_run_simulation_alone_reports_secondary_bottleneck(cfg, dfs):
    """Pipeline calls run_simulation per scenario (not run_scenarios): the flag must work there."""
    heavy_r2 = {"baseline_demand_r2": 3.0}
    assert run(S0, cfg=cfg, dfs=dfs, sys_over=heavy_r2).secondary_bottleneck is False
    assert run(Scenario("S1", [REASSIGN], []), cfg=cfg, dfs=dfs, sys_over=heavy_r2).secondary_bottleneck is True


def test_extra_amr_loss_picks_an_amr_that_is_not_already_down(cfg, dfs):
    """Adverse -1 AMR must be a REAL extra loss, not the AMR already in maintenance."""
    ev = maint("AMR03", "2026-10-08 14:00:00", "2026-10-08 15:00:00")             # AMR03 down all horizon
    only_maint = run(cfg=cfg, dfs=dfs, fc=fp(9.0), events=ev)
    fc = {"forecasts": fp(9.0), "known_events": ev, "production_plan": EMPTY_PLAN, "additional_amr_unavailable": 1}
    extra = run(cfg=cfg, dfs=dfs, fc=fc, events=None, plan=None)
    assert extra.throughput < only_maint.throughput
    idle = [a for a, u in extra.amr_utilization.items() if u == 0.0 and a in ("AMR01", "AMR02", "AMR03")]
    assert len(idle) == 2                                                          # AMR03 + one more


def test_runtime_config_is_not_mutated_and_system_section_is_used(cfg, dfs):
    import copy as _copy
    sys_cfg, thr_cfg = _copy.deepcopy(cfg)
    runtime = {"system": sys_cfg, "paths": {}, "thresholds": {}}
    before = _copy.deepcopy(runtime)
    run_simulation(None, {"forecasts": fp(), "known_events": EMPTY_EVENTS, "production_plan": EMPTY_PLAN},
                   S0, seed=1, sys_cfg=runtime, thr_cfg=thr_cfg, resource_df=dfs[0], route_df=dfs[1],
                   station_df=dfs[2], current_df=dfs[3], material_df=dfs[4])
    assert runtime == before