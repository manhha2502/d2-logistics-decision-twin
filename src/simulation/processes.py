"""
processes.py — SimPy processes (Tasks 3 & 4).

Flow per request (plan Task 3):
  Request arrival -> wait Picker -> Picking -> Staging -> wait AMR (dispatch)
  -> Loading -> Loaded travel -> Unloading -> Line buffer -> Empty return

Production consumption runs as its own process (1-min steps by default) and
records starvation start/end, starvation_minutes and unmet_consumption.

Dispatching is event driven (no polling): `dispatch()` is called whenever a
request is staged, an AMR becomes free / available, or an AMR is reassigned.
"""
from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, List

from .conditions import sim_param
from .entities import MaterialRequest

if TYPE_CHECKING:
    from .environment import SimulationEnvironment

EPS = 1e-9
AUX_MATERIAL = "AUX_MAT"


# ---------------------------------------------------------------------------
# Request schedule (built once, independent of the scenario -> common random numbers)
# ---------------------------------------------------------------------------
def build_request_schedule(sim_env: "SimulationEnvironment", rng: random.Random) -> List[MaterialRequest]:
    cond, plan = sim_env.conditions, sim_env.actions
    cfg = sim_env.sys_cfg
    main, aux = cfg["routes"]["main"], cfg["routes"]["auxiliary"]
    interval = cond.interval_min
    n_int = len(cond.routes[main])
    jitter = bool(sim_param(cfg, "arrival_jitter"))
    cv = float(sim_param(cfg, "process_noise_cv"))
    materials = sorted(sim_env.line_buffers)

    def job_size(route: str) -> float:
        js = cond.job_size.get(route, 0.0)
        if js > EPS:
            return js
        pays = [a.payload_totes for a in sim_env.amrs.values() if a.home_route == route]
        return max(pays) if pays else 1.0

    def split(total: float, route: str) -> List[float]:
        n = max(1, math.ceil(total / job_size(route) - EPS))
        return [total / n] * n

    reqs: List[MaterialRequest] = []

    # ---- queue that already exists at t=0 (current_state ROUTE.queue_end_totes) ----
    for route in (main, aux):
        q0 = sim_env.initial_backlog.get(route, 0.0)
        if q0 <= EPS:
            continue
        shares = cond.demand_share[0] if route == main else {AUX_MATERIAL: 1.0}
        for mat in (sorted(shares) if route == main else [AUX_MATERIAL]):
            part = q0 * shares[mat]
            if part <= EPS:
                continue
            for qty in split(part, route):
                reqs.append(MaterialRequest("", mat, qty, route, 0.0, 0.0, initial_backlog=True))

    # ---- future arrivals --------------------------------------------------
    for route in (main, aux):
        for k in range(n_int):
            d = cond.routes[route][k].demand
            shares = cond.demand_share[k] if route == main else {AUX_MATERIAL: 1.0}
            for mat in (materials if route == main else [AUX_MATERIAL]):
                part = d * shares.get(mat, 0.0)
                if part <= EPS:
                    continue
                parts = split(part, route)
                spacing = interval / len(parts)
                for j, qty in enumerate(parts):
                    u = rng.random() if jitter else 0.5
                    t = k * interval + (j + u) * spacing
                    noise = max(0.2, rng.gauss(1.0, cv)) if cv > 0 else 1.0
                    reqs.append(MaterialRequest("", mat, qty, route, t, t, noise=noise))

    reqs.sort(key=lambda r: (r.created_at, r.route, r.material_id))

    # ---- scenario effects applied on the fixed schedule (no extra RNG draws) ----
    alt_acc = [0.0] * len(plan.alternate)
    counters: dict = {}
    for r in reqs:
        for i, w in enumerate(plan.alternate):
            if w.route == r.route and w.active(r.created_at) and not r.initial_backlog:
                alt_acc[i] += w.value
                if alt_acc[i] >= 1.0 - EPS:
                    alt_acc[i] -= 1.0
                    r.route = w.extra["to"]
                    break
        if not r.initial_backlog:
            r.release_at = max(0.0, r.created_at - plan.release_shift(r.route, r.created_at))
        counters[r.route] = counters.get(r.route, 0) + 1
        r.request_id = f"{r.route}_req_{counters[r.route]:04d}"
    return reqs


# ---------------------------------------------------------------------------
# Request flow
# ---------------------------------------------------------------------------
def request_flow(sim_env: "SimulationEnvironment", req: MaterialRequest):
    env, cond, plan, m = sim_env.env, sim_env.conditions, sim_env.actions, sim_env.metrics
    if req.release_at > env.now + EPS:
        yield env.timeout(req.release_at - env.now)

    route = req.route
    sim_env.backlog[route] += req.quantity_totes
    if req.initial_backlog:
        yield sim_env.staging[route].container.put(req.quantity_totes)
    else:
        req.priority = plan.priority_of(req, env.now)
        with sim_env.picker.resource.request(priority=req.priority) as pr:
            yield pr
            t0 = env.now
            yield env.timeout(cond.params(route, env.now).picking * req.noise)
            m.picker_busy_time += env.now - t0
            yield sim_env.staging[route].container.put(req.quantity_totes)   # blocks (holding picker) if staging full
    req.staged_at = env.now
    sim_env.ready[route].append(req)
    dispatch(sim_env)


# ---------------------------------------------------------------------------
# Dispatch + trips
# ---------------------------------------------------------------------------
def dispatch(sim_env: "SimulationEnvironment") -> None:
    env, plan = sim_env.env, sim_env.actions
    for amr in sorted(sim_env.amrs.values(), key=lambda a: a.amr_id):
        if amr.on_trip or not amr.available:
            continue
        queue = sim_env.ready.get(amr.route)
        if not queue:
            continue
        t = env.now
        queue.sort(key=lambda r: (plan.priority_of(r, t), r.release_at, r.request_id))
        batch = [queue.pop(0)]
        cap = plan.max_batch(amr.route, t)
        if cap is not None:
            cap = min(cap, amr.payload_totes)
            total = batch[0].quantity_totes
            for r in list(queue):
                if total + r.quantity_totes <= cap + EPS:
                    batch.append(r)
                    queue.remove(r)
                    total += r.quantity_totes
        amr.on_trip = True
        amr.trip_start = t
        amr.trip_route = amr.route
        env.process(trip_process(sim_env, amr, batch))


def trip_process(sim_env: "SimulationEnvironment", amr, batch: List[MaterialRequest]):
    env, cond, m = sim_env.env, sim_env.conditions, sim_env.metrics
    route = batch[0].route
    noise = batch[0].noise
    total = sum(r.quantity_totes for r in batch)

    for r in batch:                                   # AMR picks the load up from staging
        r.served_at = env.now
        sim_env.backlog[route] -= r.quantity_totes
    stg = sim_env.staging[route].container
    take = min(total, stg.level)
    if take > EPS:
        yield stg.get(take)

    yield env.timeout(cond.params(route, env.now).loading * noise)
    yield env.timeout(cond.params(route, env.now).travel_loaded * noise)
    yield env.timeout(cond.params(route, env.now).unloading * noise)

    for r in batch:                                   # unload into line buffer
        r.completed_at = env.now
        buf = sim_env.line_buffers.get(r.material_id)
        if buf is None:                               # auxiliary area: no modelled buffer
            m.record_delivery(route, r.quantity_totes)
            continue
        space = buf.container.capacity - buf.container.level
        deliver = max(0.0, min(r.quantity_totes, space))
        if deliver > EPS:
            yield buf.container.put(deliver)
        if r.quantity_totes - deliver > EPS:
            m.buffer_overflow += r.quantity_totes - deliver
        m.record_delivery(route, deliver)

    yield env.timeout(cond.params(route, env.now).travel_empty * noise)   # empty return

    trip_t0 = amr.trip_start
    amr.busy_time += env.now - trip_t0
    m.busy_by_route[route] = m.busy_by_route.get(route, 0.0) + env.now - trip_t0
    amr.trip_start = None
    amr.on_trip = False
    m.trips_completed[route] = m.trips_completed.get(route, 0) + 1
    m.trip_log.append((amr.amr_id, route, round(trip_t0, 4), round(env.now, 4), round(total, 4)))
    dispatch(sim_env)


# ---------------------------------------------------------------------------
# Production consumption (Task 3 + 4)
# ---------------------------------------------------------------------------
def production_consumption_process(sim_env: "SimulationEnvironment"):
    env, cond, m = sim_env.env, sim_env.conditions, sim_env.metrics
    step = float(sim_param(sim_env.sys_cfg, "consumption_step_min"))
    n = int(round(cond.horizon_min / step))
    open_events: dict = {}
    for mat, buf in sim_env.line_buffers.items():
        m.buffer_min_level[mat] = buf.container.level

    for _ in range(n):
        yield env.timeout(step)
        any_short = False
        for mat, buf in sim_env.line_buffers.items():
            need = cond.consumption_rate(mat, env.now - step) * step / cond.interval_min
            if need <= EPS:
                continue
            take = min(buf.container.level, need)
            if take > EPS:
                yield buf.container.get(take)
            m.buffer_min_level[mat] = min(m.buffer_min_level[mat], buf.container.level)
            short = need - take
            if short > EPS:
                any_short = True
                m.unmet_consumption += short
                m.unmet_by_material[mat] = m.unmet_by_material.get(mat, 0.0) + short
                open_events.setdefault(mat, env.now - step)
            elif mat in open_events:
                m.starvation_events.append((mat, open_events.pop(mat), env.now - step))
        if any_short:
            m.starvation_minutes += step   # starvation_minutes is tracked per-system
    for mat, start in open_events.items():
        m.starvation_events.append((mat, start, env.now))


# ---------------------------------------------------------------------------
# Monitors / availability
# ---------------------------------------------------------------------------
def queue_monitor_process(sim_env: "SimulationEnvironment"):
    env, cond, m = sim_env.env, sim_env.conditions, sim_env.metrics
    step = float(sim_param(sim_env.sys_cfg, "queue_sample_min"))
    n = int(round(cond.horizon_min / step))
    per_interval = max(1, int(round(cond.interval_min / step)))
    for i in range(n + 1):
        for route, q in sim_env.backlog.items():
            m.record_queue(route, max(0.0, q))
            if i < n:
                pool = sum(1 for a in sim_env.amrs.values() if a.route == route and a.available)
                m.pool_minutes[route] = m.pool_minutes.get(route, 0.0) + pool * step
            if i > 0 and i % per_interval == 0:
                m.record_interval_queue(route, max(0.0, q))
        yield env.timeout(step)


def availability_process(sim_env: "SimulationEnvironment", window):
    """Known maintenance: AMR not dispatchable inside the window (running trip finishes first)."""
    env = sim_env.env
    amr = sim_env.amrs.get(window.amr_id)
    if amr is None:
        return
    if window.start_min > env.now:
        yield env.timeout(window.start_min - env.now)
    amr.set_available(env.now, False)
    if window.end_min > env.now:
        yield env.timeout(window.end_min - env.now)
    amr.set_available(env.now, amr.base_available)
    dispatch(sim_env)
