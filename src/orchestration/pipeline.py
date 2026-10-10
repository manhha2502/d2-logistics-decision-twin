"""End-to-end orchestration. No production mocks or synthetic KPI fallback.

Upstream adapter contracts are documented in README. Existing shared schemas
and other owners' files remain unchanged.
"""
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any
from uuid import uuid4
import csv
import json
import threading

import pandas as pd

from src.common.config import load_config
from src.common.schemas import (ForecastPoint, FutureState, BottleneckEvent, Cause,
                                Scenario, SimulationResult, DecisionPackage)
from src.actions.scenario_generator import generate_scenarios
from src.actions.feasibility import check_static_feasibility
from src.evaluation.constraints import apply_dynamic_constraints
from src.evaluation.pareto import filter_pareto_front
from src.evaluation.kpi_compare import compare_kpi_vs_baseline
from src.evaluation.robustness import rank_scenarios, evaluate_robustness
from src.recommendation.builder import build_decision_package

UPSTREAM = {
    "forecast": ("src.forecast.service", "forecast_future_drivers"),
    "future_state": ("src.logistics.future_state", "build_future_states"),
    "bottleneck": ("src.bottleneck.detector", "detect_bottlenecks"),
    "diagnose": ("src.bottleneck.cause_diagnosis", "diagnose_causes"),
    "simulate": ("src.simulation.simulator", "run_simulation"),
}


class PipelineError(RuntimeError):
    """An actionable stage failure with the original exception preserved."""


@dataclass
class PipelineResult:
    run_id: str
    now: datetime
    decision_mode: str
    seed: int
    status: str = ""
    current_state: pd.DataFrame = field(default_factory=pd.DataFrame)
    forecasts: list[ForecastPoint] = field(default_factory=list)
    future_states: list[FutureState] = field(default_factory=list)
    bottlenecks: list[BottleneckEvent] = field(default_factory=list)
    causes: list[Cause] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    simulation_results: dict[str, SimulationResult] = field(default_factory=dict)
    results_by_condition: dict[str, dict[str, SimulationResult]] = field(default_factory=dict)
    rejected_scenarios: dict[str, list[str]] = field(default_factory=dict)
    ranked_scenarios: list[tuple[str, float]] = field(default_factory=list)
    kpi_comparison: dict[str, Any] = field(default_factory=dict)
    robustness: dict[str, Any] = field(default_factory=dict)
    decision_package: DecisionPackage | None = None


def module_readiness():
    """Return missing upstream APIs without importing mocks."""
    missing = []
    for stage, (module, name) in UPSTREAM.items():
        try:
            if not callable(getattr(import_module(module), name, None)):
                missing.append(f"{stage}: {module}.{name} is not implemented")
        except Exception as exc:
            missing.append(f"{stage}: cannot import {module}: {exc}")
    return missing


def _call(stage, function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        raise PipelineError(f"Stage '{stage}' failed: {exc}") from exc


def _schema_list(stage, value, schema):
    if not isinstance(value, list) or any(not isinstance(item, schema) for item in value):
        raise PipelineError(f"{stage} must return list[{schema.__name__}]")
    return value


def _resolve(stage):
    module, name = UPSTREAM[stage]
    try:
        function = getattr(import_module(module), name)
    except (ImportError, AttributeError) as exc:
        raise PipelineError(f"Missing upstream API: {module}.{name}. Implement this module before running the real pipeline.") from exc
    return function


def _read_inputs(config):
    paths = config["paths"]
    current = pd.read_csv(paths["current_state"])
    required = {"entity_type", "entity_id", "metric", "value"}
    if current.empty or not required.issubset(current.columns):
        raise ValueError(f"current_state requires non-empty columns: {sorted(required)}")
    if current[list(required)].isna().any().any():
        raise ValueError("current_state contains missing fields")
    if current.duplicated(["entity_type", "entity_id", "metric"]).any():
        raise ValueError("Duplicate current-state metrics")
    events = pd.read_csv(paths["known_events"], parse_dates=["start_time", "end_time"])
    if (events["end_time"] < events["start_time"]).any():
        raise ValueError("Known event ends before its start")
    plan = pd.read_csv(paths["production_plan"], parse_dates=["timestamp"])
    return current, events, plan


def run_pipeline(decision_mode="balanced", now=None, seed=42):
    """Run real modules. Default now is the configured data snapshot time."""
    config = _call("configuration", load_config)
    # Resolve real forecast first; missing implementations must never pass as a demo.
    _resolve("forecast")
    if config["readiness_warnings"]:
        raise PipelineError("Incomplete runtime configuration: " + "; ".join(config["readiness_warnings"]))
    return _execute(config, decision_mode, now, seed)


def _execute(config, decision_mode="balanced", now=None, seed=42, *, services=None):
    """Internal dependency seam for tests only; dashboard never supplies services."""
    if decision_mode not in config["decision"]["decision_modes"]:
        raise PipelineError(f"Unknown decision mode: {decision_mode}")
    if type(seed) is not int:
        raise PipelineError("seed must be an integer")
    try:
        now = pd.Timestamp(now if now is not None else config["system"]["snapshot_time"]).to_pydatetime()
    except (ValueError, TypeError) as exc:
        raise PipelineError(f"Invalid snapshot timestamp: {now}") from exc
    if now.tzinfo is not None:
        from zoneinfo import ZoneInfo
        now = now.astimezone(ZoneInfo(config["system"]["timezone"])).replace(tzinfo=None)
    if pd.isna(now):
        raise PipelineError("now must be a valid timestamp")
    def service(stage):
        return services[stage] if services is not None else _resolve(stage)
    result = PipelineResult(uuid4().hex, now, decision_mode, seed)
    current, events, plan = _call("load current state", _read_inputs, config)
    result.current_state = current
    # Context is passed to logistics and simulation; no validation_only reads.
    context = dict(config, production_plan=plan, known_events=events, now=now)
    forecasts = _call("forecast", service("forecast"), now,
                      horizon_min=config["system"]["horizon_min"],
                      interval_min=config["system"]["interval_min"])
    result.forecasts = _schema_list("forecast", forecasts, ForecastPoint)
    expected_times = {now + pd.Timedelta(minutes=n) for n in (15, 30, 45, 60)}
    if len(forecasts) != 4 or {f.timestamp for f in forecasts} != expected_times:
        raise PipelineError("Forecast timestamps must be exactly +15/+30/+45/+60")
    for forecast in forecasts:
        for name in ("demand", "travel_loaded", "travel_empty", "picking_time", "loading_time", "unloading_time"):
            q = getattr(forecast, name)
            if not (0 <= q.p10 <= q.p50 <= q.p90 < float("inf")):
                raise PipelineError(f"Invalid forecast quantiles: {name}")
    states = _call("future state", service("future_state"), current, forecasts, events, context)
    result.future_states = _schema_list("future state", states, FutureState)
    if len(states) != 8 or {(s.location, s.timestamp) for s in states} != {
        (route, stamp) for route in ("R1", "R2") for stamp in expected_times
    }:
        raise PipelineError("Future states must cover R1/R2 at all four forecast timestamps")
    events_found = _call("bottleneck", service("bottleneck"), states, context)
    result.bottlenecks = _schema_list("bottleneck", events_found, BottleneckEvent)
    if not events_found:
        result.status = "No intervention required"
        result.scenarios = [Scenario("S0", [], [])]
        return result
    causes = _call("cause diagnosis", service("diagnose"), events_found, current, forecasts, events, context)
    result.causes = _schema_list("cause diagnosis", causes, Cause)
    scenarios = _call("scenario generation", generate_scenarios, causes,
                      current_state_df=current, master_dir=config["paths"]["master_dir"],
                      config_path=config["config_paths"]["actions"],
                      max_scenarios=config["system"]["max_scenarios"])
    for scenario in scenarios:
        feasibility = _call("static feasibility", check_static_feasibility, scenario,
                            current_state_df=current, master_dir=config["paths"]["master_dir"],
                            config_path=config["config_paths"]["actions"])
        if feasibility.is_feasible:
            result.scenarios.append(scenario)
        else:
            result.rejected_scenarios[scenario.scenario_id] = feasibility.rejection_reasons
    if not any(s.scenario_id == "S0" and not s.actions for s in result.scenarios):
        raise PipelineError("Scenario generation must include baseline S0")
    simulate = service("simulate")
    robust_cfg = config["decision"]["robustness"]
    def simulate_condition(condition, candidates):
        future = {"condition": condition, "quantile": {"expected": "p50", "favorable": "p10", "adverse": "p90"}[condition],
                  "forecasts": forecasts, "known_events": events.copy(deep=True),
                  "production_plan": plan.copy(deep=True), "config": context,
                  "additional_amr_unavailable": (int(robust_cfg.get("adverse_reduce_amr_count", 0))
                      if condition == "adverse" and robust_cfg.get("enable_adverse_amr_reduction", False) else 0)}
        outputs = {}
        for scenario in candidates:
            # Isolate input mutation by third-party process implementations.
            from copy import deepcopy
            output = _call(f"simulation/{condition}/{scenario.scenario_id}", simulate,
                           current.copy(deep=True), deepcopy(future), deepcopy(scenario), seed=seed)
            if not isinstance(output, SimulationResult) or output.scenario_id != scenario.scenario_id:
                raise PipelineError(f"Simulation must return matching SimulationResult for {scenario.scenario_id}")
            import math
            metrics = (output.avg_waiting_time, output.max_waiting_time, output.avg_queue,
                       output.max_queue, output.late_delivery_count, output.throughput,
                       output.service_level, output.starvation_minutes, output.unmet_consumption,
                       output.buffer_overflow, *output.amr_utilization.values())
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in metrics):
                raise PipelineError(f"Invalid numeric simulation metrics for {scenario.scenario_id}")
            outputs[scenario.scenario_id] = output
        return outputs
    result.simulation_results = simulate_condition("expected", result.scenarios)
    decision_path = config["config_paths"]["decision"]
    valid, rejected = _call("dynamic constraints", apply_dynamic_constraints,
                            result.scenarios, result.simulation_results, config_path=decision_path)
    result.rejected_scenarios.update(rejected)
    result.kpi_comparison = {s.scenario_id: _call("KPI comparison", compare_kpi_vs_baseline,
        result.simulation_results[s.scenario_id], result.simulation_results["S0"], s)
        for s in result.scenarios}
    pareto = _call("Pareto", filter_pareto_front, valid, result.simulation_results)
    ranked = _call("ranking", rank_scenarios, pareto, result.simulation_results,
                   decision_mode=decision_mode, config_path=decision_path)
    result.ranked_scenarios = [(s.scenario_id, score) for s, score in ranked]
    top = [s for s, _ in ranked if s.scenario_id != "S0"][:robust_cfg["top_k_scenarios"]]
    baseline = next(s for s in result.scenarios if s.scenario_id == "S0")
    candidates = [baseline] + top
    result.results_by_condition = {"expected": result.simulation_results}
    for condition in ("favorable", "adverse"):
        result.results_by_condition[condition] = simulate_condition(condition, candidates)
    result.robustness = _call("robustness", evaluate_robustness, candidates, result.results_by_condition,
                              decision_mode=decision_mode, config_path=decision_path)
    severity_order = {"LOW": 0, "NORMAL": 0, "WARNING": 1, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    primary = max(events_found, key=lambda b: (severity_order.get(b.severity.upper(), 0), b.risk_score, -b.lead_time_min))
    result.decision_package = _call("recommendation", build_decision_package,
        bottleneck=primary, causes=causes, scenarios=result.scenarios,
        sim_results=result.simulation_results, decision_mode=decision_mode,
        sim_results_by_condition=result.results_by_condition, config_path=decision_path)
    chosen = result.decision_package.recommended_scenario.scenario_id
    if chosen in result.rejected_scenarios:
        raise PipelineError("Recommendation selected a rejected scenario")
    result.status = "Recommendation ready" if chosen != "S0" else "No safe intervention selected"
    return result


def _json_default(value):
    if isinstance(value, pd.DataFrame):
        return value.to_dict("records")
    if isinstance(value, (datetime, Path)):
        return str(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def save_run(result, config=None):
    """Persist a completed run with its seed, snapshot, inputs and outputs."""
    config = config or load_config()
    folder = config["paths"]["artifacts_dir"] / "recommendations"
    folder.mkdir(parents=True, exist_ok=True)
    if not result.run_id.isalnum():
        raise ValueError("Invalid run ID")
    target = folder / f"{result.run_id}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(result), default=_json_default, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(target)
    return target


_decision_lock = threading.Lock()


def record_operator_decision(result, decision, notes="", config=None):
    """Audit the human decision only; never send commands to real equipment."""
    if decision not in {"APPROVE", "MODIFY", "REJECT"}:
        raise ValueError("Unknown operator decision")
    if result.decision_package is None:
        raise ValueError("No recommendation is available for operator decision")
    if decision == "MODIFY" and not notes.strip():
        raise ValueError("Describe the requested modification")
    config = config or load_config()
    from zoneinfo import ZoneInfo
    row = {"timestamp": datetime.now(ZoneInfo(config["system"]["timezone"])).isoformat(),
           "run_id": result.run_id, "snapshot_time": result.now.isoformat(),
           "decision_mode": result.decision_mode, "seed": result.seed,
           "scenario_id": result.decision_package.recommended_scenario.scenario_id,
           "decision": decision, "notes": notes}
    path = config["paths"]["artifacts_dir"] / "operator_decisions.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Prevent spreadsheet formula execution when this audit CSV is opened.
    for key, value in row.items():
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            row[key] = "'" + value
    with _decision_lock:
        exists = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            if not exists:
                writer.writeheader()
            writer.writerow(row)
    return path
