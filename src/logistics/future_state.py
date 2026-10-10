"""Build deterministic P50 logistics states for R1 and R2."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.common.schemas import ForecastPoint, FutureState
from src.logistics.buffer import update_buffer
from src.logistics.capacity import calculate_transport_capacity
from src.logistics.queue import calculate_queue_state

ROOT = Path(__file__).resolve().parents[2]


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return pd.read_csv(value).to_dict("records")
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, dict):
        return [value]
    return [asdict(row) if is_dataclass(row) else dict(row) for row in value]


def _master_records(value: Any, id_field: str) -> list[dict[str, Any]]:
    """Accept CSV/dataframe/list records or a mapping keyed by master ID."""
    if isinstance(value, dict) and id_field not in value:
        records = []
        for identifier, fields in value.items():
            if isinstance(fields, dict):
                records.append({id_field: identifier, **fields})
        return records
    return _records(value)


def _metric_map(current_state: Any) -> dict[tuple[str, str, str], Any]:
    if isinstance(current_state, dict) and not {"entity_type", "entity_id", "metric", "value"}.issubset(current_state):
        result: dict[tuple[str, str, str], Any] = {}
        for entity_id, metrics in current_state.items():
            if not isinstance(metrics, dict):
                continue
            kind = "ROUTE" if str(entity_id).startswith("R") else "BUFFER" if str(entity_id).startswith("MAT") else "RESOURCE"
            for metric, value in metrics.items():
                result[kind, str(entity_id), str(metric)] = value
        return result
    result = {}
    for row in _records(current_state):
        result[str(row["entity_type"]).upper(), str(row["entity_id"]), str(row["metric"])] = row["value"]
    return result


def _number(metrics: dict, kind: str, entity: str, name: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get((kind, entity, name), default))
    except (TypeError, ValueError):
        return default


def _active_events(events: list[dict[str, Any]], timestamp: datetime) -> list[dict[str, Any]]:
    active = []
    ts = pd.Timestamp(timestamp)
    for event in events:
        start = pd.Timestamp(event.get("start_time", datetime.min))
        end = pd.Timestamp(event.get("end_time", datetime.max))
        if start <= ts < end:
            active.append(event)
    return active


def _cfg(config: dict[str, Any], name: str, default: Any) -> Any:
    return config.get(name, config.get("logistics", {}).get(name, default))


def _r2_baseline_times(source: Any, before: pd.Timestamp) -> dict[str, float]:
    """Use only process observations available before the forecast origin."""
    rows = [
        row for row in _records(source)
        if str(row.get("route_id")) == "R2" and pd.Timestamp(row["timestamp"]) < before
    ]
    if not rows:
        raise ValueError("R2 needs process history before the forecast origin")
    latest = max(rows, key=lambda row: pd.Timestamp(row["timestamp"]))
    return {
        "loading_time": float(latest["loading_min"]),
        "travel_loaded": float(latest["travel_loaded_min"]),
        "unloading_time": float(latest["unloading_min"]),
        "travel_empty": float(latest["travel_empty_min"]),
    }


def _production_plan(source: Any) -> dict[pd.Timestamp, dict[str, Any]]:
    return {
        pd.Timestamp(row["timestamp"]): row
        for row in _records(source)
        if str(row.get("line_id")) == "LINE_A"
    }


def build_future_states(
    current_state: Any,
    forecasts: Iterable[ForecastPoint],
    known_events: Any = None,
    config: dict[str, Any] | None = None,
) -> list[FutureState]:
    """Create R1/R2 states at every supplied forecast timestamp.

    Forecast P50 values belong to R1. R2 demand follows its current DCR and
    known event multipliers, as required by the MVP forecast scope.
    """
    config = config or {}
    forecast_points = sorted(forecasts, key=lambda point: point.timestamp)
    if len(forecast_points) != 4:
        raise ValueError("MVP forecasts must contain exactly +15/+30/+45/+60 points")
    timestamps = [pd.Timestamp(point.timestamp) for point in forecast_points]
    if any((later - earlier).total_seconds() != 15 * 60 for earlier, later in zip(timestamps, timestamps[1:])):
        raise ValueError("MVP forecast timestamps must be unique consecutive 15-minute intervals")
    configured_now = _cfg(config, "now", None)
    if configured_now is not None:
        expected = [pd.Timestamp(configured_now) + pd.Timedelta(minutes=minutes) for minutes in (15, 30, 45, 60)]
        if timestamps != expected:
            raise ValueError("forecast timestamps must equal now +15/+30/+45/+60")

    metrics = _metric_map(current_state)
    events = _records(known_events)
    if known_events is None:
        default_events = ROOT / "data/known_future/known_future_events.csv"
        events = _records(default_events) if default_events.exists() else []

    route_source = _cfg(config, "routes", _cfg(config, "route_master", ROOT / "data/master/route_master.csv"))
    resource_source = _cfg(config, "resources", _cfg(config, "resource_master", ROOT / "data/master/resource_master.csv"))
    material_source = _cfg(config, "materials", _cfg(config, "material_master", ROOT / "data/master/material_master.csv"))
    route_rows = _master_records(route_source, "route_id")
    resource_rows = _master_records(resource_source, "resource_id")
    material_rows = _master_records(material_source, "material_id")
    routes = {str(row["route_id"]): row for row in route_rows}
    materials = {str(row["material_id"]): row for row in material_rows}
    if not {"R1", "R2"}.issubset(routes):
        raise ValueError("route configuration must contain R1 and R2")

    available_by_route: dict[str, list[str]] = {"R1": [], "R2": []}
    for resource in resource_rows:
        rid = str(resource["resource_id"])
        route = str(metrics.get(("RESOURCE", rid, "route_id"), resource["home_route"]))
        if _number(metrics, "RESOURCE", rid, "available", 1) > 0 and route in available_by_route:
            available_by_route[route].append(rid)

    queue = {route: _number(metrics, "ROUTE", route, "queue_end_totes") for route in routes}
    current_dcr = {route: _number(metrics, "ROUTE", route, "dcr", 0.5) for route in routes}
    buffers = {
        material: _number(metrics, "BUFFER", material, "current_level_totes", float(row["buffer_capacity_totes"]) / 2)
        for material, row in materials.items()
    }
    load_factor = float(_cfg(config, "load_factor", 0.85))
    window_min = float(_cfg(config, "window_min", 15.0))
    origin = pd.Timestamp(configured_now) if configured_now is not None else timestamps[0] - pd.Timedelta(minutes=window_min)
    history_source = _cfg(config, "r2_process_history", ROOT / "data/history/process_history_15min.csv")
    r2_times = _r2_baseline_times(history_source, origin)
    r2_times.update(_cfg(config, "r2_process_times", {}))
    plan_source = _cfg(config, "production_plan", ROOT / "data/known_future/future_production_plan_15min.csv")
    production_plan = _production_plan(plan_source)
    material_weights = {
        material: float(row["units_per_product"]) / float(row["units_per_tote"])
        for material, row in materials.items() if material in {"MAT_A", "MAT_B"}
    }
    if set(material_weights) != {"MAT_A", "MAT_B"} or sum(material_weights.values()) <= 0:
        raise ValueError("material master must define positive MAT_A and MAT_B usage")
    default_shares = {name: weight / sum(material_weights.values()) for name, weight in material_weights.items()}
    output: list[FutureState] = []

    for forecast in forecast_points:
        active = _active_events(events, forecast.timestamp)
        route_calcs: dict[str, dict[str, float]] = {}
        for route_id in ("R1", "R2"):
            route = routes[route_id]
            unavailable = {
                str(event.get("target_id"))
                for event in active
                if str(event.get("event_type", "")).upper() in {"AMR_MAINTENANCE", "AMR_FAILURE"}
            }
            amr_available = sum(rid not in unavailable for rid in available_by_route[route_id])
            if route_id == "R1":
                demand = float(forecast.demand.p50)
                loading = float(forecast.loading_time.p50)
                loaded = float(forecast.travel_loaded.p50)
                unloading = float(forecast.unloading_time.p50)
                empty = float(forecast.travel_empty.p50)
            else:
                loading = float(r2_times["loading_time"])
                loaded = float(r2_times["travel_loaded"])
                unloading = float(r2_times["unloading_time"])
                empty = float(r2_times["travel_empty"])
                nominal_capacity = calculate_transport_capacity(
                    len(available_by_route[route_id]), float(route["payload_totes_per_amr"]), load_factor,
                    window_min, loading, loaded, unloading, empty,
                )
                demand = current_dcr[route_id] * nominal_capacity
                for event in active:
                    if str(event.get("target_id")) == route_id and str(event.get("event_type", "")).upper() in {"AUX_ROUTE_PEAK", "DEMAND_SURGE"}:
                        demand *= float(event.get("magnitude", 1.0))
            capacity = calculate_transport_capacity(
                amr_available, float(route["payload_totes_per_amr"]), load_factor,
                window_min, loading, loaded, unloading, empty,
            )
            queue_start = queue[route_id]
            q = calculate_queue_state(queue_start, demand, capacity, float(route["staging_capacity_totes"]))
            queue[route_id] = q["queue_end"]
            utilization = min(1.0, q["throughput"] / capacity) if capacity else (1.0 if demand or queue[route_id] else 0.0)
            waiting = queue[route_id] / capacity * window_min if capacity else (window_min if queue[route_id] else 0.0)
            route_calcs[route_id] = {
                **q, "queue_start": queue_start, "demand": demand, "capacity": capacity,
                "dcr": demand / capacity if capacity else (float("inf") if demand else 0.0),
                "utilization": utilization, "waiting": waiting, "amr_available": amr_available,
            }

        # The known line plan determines material consumption. Forecast demand is
        # already the R1 driver, so PRODUCTION_RAMP is not multiplied a second time.
        plan_row = production_plan.get(pd.Timestamp(forecast.timestamp))
        planned_consumption = {
            "MAT_A": float(plan_row["planned_mat_a_totes"]),
            "MAT_B": float(plan_row["planned_mat_b_totes"]),
        } if plan_row else {}
        plan_total = sum(planned_consumption.values())
        shares = _cfg(config, "material_shares", None)
        if shares is None:
            shares = (
                {name: amount / plan_total for name, amount in planned_consumption.items()}
                if plan_total > 0 else default_shares
            )
        consumption = _cfg(config, "consumption_per_window", {})
        buffer_results = {}
        for material in ("MAT_A", "MAT_B"):
            if material not in materials:
                continue
            amount = float(consumption.get(
                material, planned_consumption.get(material, forecast.demand.p50 * float(shares[material]))
            ))
            result = update_buffer(
                buffers[material], route_calcs["R1"]["throughput"] * float(shares[material]),
                amount, float(materials[material]["buffer_capacity_totes"]),
            )
            buffers[material] = result["next_level"]
            buffer_results[material] = result
        unmet = sum(item["unmet_consumption"] for item in buffer_results.values())
        buffer_overflow = sum(item["overflow"] for item in buffer_results.values())

        for route_id in ("R1", "R2"):
            calc = route_calcs[route_id]
            output.append(FutureState(
                timestamp=forecast.timestamp, location=route_id, demand=calc["demand"], capacity=calc["capacity"],
                dcr=calc["dcr"], throughput=calc["throughput"], queue_start=calc["queue_start"],
                queue_end=calc["queue_end"], waiting_time=calc["waiting"], utilization=calc["utilization"],
                buffer_mat_a=buffers.get("MAT_A", 0.0), buffer_mat_b=buffers.get("MAT_B", 0.0),
                unmet_consumption=unmet if route_id == "R1" else 0.0,
                overflow=calc["overflow"] + (buffer_overflow if route_id == "R1" else 0.0),
                amr_available=int(calc["amr_available"]),
            ))
    return output
