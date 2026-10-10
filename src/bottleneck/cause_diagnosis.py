"""Transparent rule-based (not causal-ML) bottleneck diagnosis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.bottleneck.hard_rules import DEFAULT_CONFIG, _overflow_parts, load_thresholds
from src.common.schemas import Cause, ForecastPoint, FutureState


def _event_records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return pd.read_csv(value).to_dict("records")
    if hasattr(value, "to_dict"):
        return value.to_dict("records")
    if isinstance(value, dict):
        return [value]
    return [dict(item) for item in value]


def _value(obj: Any, name: str, default: float = 0.0) -> float:
    if obj is None:
        return float(default)
    if isinstance(obj, dict):
        return float(obj.get(name, default))
    return float(getattr(obj, name, default))


def _forecast_value(forecast: Any, name: str) -> float | None:
    if forecast is None:
        return None
    value = forecast.get(name) if isinstance(forecast, dict) else getattr(forecast, name, None)
    if value is None:
        return None
    if isinstance(value, dict):
        return float(value.get("p50", value.get("value", 0.0)))
    return float(getattr(value, "p50", value))


def _increase(baseline: float, forecast: float) -> float:
    return ((forecast - baseline) / baseline * 100.0) if baseline else (100.0 if forecast > 0 else 0.0)


def diagnose_causes(
    state: FutureState,
    baseline: FutureState | dict[str, Any] | None = None,
    forecast: ForecastPoint | dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    known_events: Any = None,
) -> list[Cause]:
    """Return every supported cause with concrete baseline/forecast evidence."""
    cfg = load_thresholds(config)
    diagnosis = cfg.get("diagnosis", {})
    demand_pct = float(diagnosis["demand_increase_pct"])
    process_pct = float(diagnosis["process_increase_pct"])
    causes: list[Cause] = []

    # An absent baseline cannot establish a demand increase. Do not synthesize
    # one from capacity, which would fabricate a DEMAND_SPIKE cause.
    base_demand = _value(baseline, "demand", state.demand)
    if state.demand > base_demand and _increase(base_demand, state.demand) >= demand_pct:
        causes.append(Cause("DEMAND_SPIKE", "High", {
            "baseline": base_demand, "forecast": state.demand,
            "increase_pct": round(_increase(base_demand, state.demand), 2),
        }))

    base_amr = int(_value(baseline, "amr_available", state.amr_available))
    if state.amr_available < base_amr:
        causes.append(Cause("AMR_AVAILABILITY_DROP", "High", {
            "baseline": base_amr, "forecast": state.amr_available,
            "decrease_pct": round((base_amr - state.amr_available) / base_amr * 100.0, 2) if base_amr else 0.0,
        }))
    elif known_events is not None:
        root = DEFAULT_CONFIG.parents[1]
        resource_source = (config or {}).get("resources", root / "data/master/resource_master.csv")
        resources = _event_records(resource_source)
        resource_routes = {str(row["resource_id"]): str(row["home_route"]) for row in resources}
        resource_routes.update((config or {}).get("resource_routes", {}))
        for event in _event_records(known_events):
            event_type = str(event.get("event_type", "")).upper()
            resource_id = str(event.get("target_id", ""))
            if resource_routes.get(resource_id) != state.location:
                continue
            start = event.get("start_time")
            end = event.get("end_time")
            try:
                active = (start is None or state.timestamp >= pd.Timestamp(start)) and (
                    end is None or state.timestamp < pd.Timestamp(end)
                )
            except (TypeError, ValueError):
                active = False
            if active and event_type in {"AMR_MAINTENANCE", "AMR_FAILURE"}:
                drop = max(1, int(float(event.get("magnitude", 1))))
                baseline_amr = state.amr_available + drop
                causes.append(Cause("AMR_AVAILABILITY_DROP", "High", {
                    "baseline": baseline_amr, "forecast": state.amr_available,
                    "decrease_pct": round(drop / baseline_amr * 100.0, 2),
                    "resource_id": resource_id, "event_type": event_type,
                }))
                break

    predicted_travel = [_forecast_value(forecast, name) for name in ("travel_loaded", "travel_empty")]
    baseline_travel = [_forecast_value(baseline, name) for name in ("travel_loaded", "travel_empty")]
    available_predicted = [value for value in predicted_travel if value is not None]
    available_baseline = [value for value in baseline_travel if value is not None]
    if available_predicted and len(available_predicted) == len(available_baseline):
        travel_total, base_travel_total = sum(available_predicted), sum(available_baseline)
        if _increase(base_travel_total, travel_total) >= process_pct:
            causes.append(Cause("TRAVEL_TIME_INCREASE", "High", {
                "baseline": base_travel_total, "forecast": travel_total,
                "increase_pct": round(_increase(base_travel_total, travel_total), 2),
            }))

    comparisons = [("PICKING_SLOWDOWN", "picking_time", "picking_time", "Medium")]
    for cause_type, forecast_name, baseline_name, contribution in comparisons:
        predicted = _forecast_value(forecast, forecast_name)
        base = _forecast_value(baseline, baseline_name)
        if predicted is not None and base is not None and _increase(base, predicted) >= process_pct:
            causes.append(Cause(cause_type, contribution, {
                "baseline": base, "forecast": predicted,
                "increase_pct": round(_increase(base, predicted), 2),
            }))

    predicted_handling_values = [_forecast_value(forecast, name) for name in ("loading_time", "unloading_time")]
    baseline_handling_values = [_forecast_value(baseline, name) for name in ("loading_time", "unloading_time")]
    if None not in predicted_handling_values + baseline_handling_values:
        predicted_handling = sum(predicted_handling_values)  # type: ignore[arg-type]
        base_handling = sum(baseline_handling_values)  # type: ignore[arg-type]
        if _increase(base_handling, predicted_handling) >= process_pct:
            causes.append(Cause("HANDLING_TIME_INCREASE", "Medium", {
                "baseline": base_handling, "forecast": predicted_handling,
                "increase_pct": round(_increase(base_handling, predicted_handling), 2),
            }))

    if state.location == "R1":
        buffer = cfg["buffer"]
        ratios = {
            "MAT_A": state.buffer_mat_a / float(buffer["capacity_mat_a"]),
            "MAT_B": state.buffer_mat_b / float(buffer["capacity_mat_b"]),
        }
        low = {name: ratio for name, ratio in ratios.items() if ratio <= float(buffer["low_ratio"])}
        full = {name: ratio for name, ratio in ratios.items() if ratio >= float(buffer["full_ratio"])}
        buffer_overflow = _overflow_parts(state)[1]
        if low or state.unmet_consumption > 0:
            causes.append(Cause("BUFFER_LOW", "High" if state.unmet_consumption else "Medium", {
                "buffer_ratios": low, "threshold": float(buffer["low_ratio"]),
                "unmet_consumption": state.unmet_consumption,
            }))
        if full or buffer_overflow > 0:
            causes.append(Cause("BUFFER_FULL", "Medium", {
                "buffer_ratios": full, "threshold": float(buffer["full_ratio"]),
                "overflow": buffer_overflow,
            }))
    return causes


diagnose_bottleneck_causes = diagnose_causes
