"""Integration tests: real Quân engine with explicit upstream test doubles.

These are orchestration tests, not validation of Dương/Hà/Phú algorithms.
No mock is reachable through run_pipeline() or the dashboard.
"""
from dataclasses import replace
from datetime import timedelta
import csv
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from src.common.config import load_config, ConfigError
from src.common.schemas import (QuantileValue, ForecastPoint, FutureState,
                                BottleneckEvent, Cause, SimulationResult)
from src.orchestration.pipeline import (_execute, run_pipeline, PipelineError,
    module_readiness, save_run, record_operator_decision)


@pytest.fixture
def config(tmp_path):
    cfg = load_config()
    cfg["paths"]["artifacts_dir"] = tmp_path / "artifacts"
    return cfg


def services(case="demand", secondary=False):
    def forecast(now, horizon_min, interval_min):
        return [ForecastPoint(now + timedelta(minutes=n), *[
            QuantileValue(6, 8, 12) for _ in range(6)]) for n in range(interval_min, horizon_min+1, interval_min)]
    def future(current, forecasts, events, config):
        return [FutureState(f.timestamp, route, f.demand.p50, 7, 8/7, 7,
                            1, 2, 3, .8, 10, 10, 0, 0, 2)
                for f in forecasts for route in ("R1", "R2")]
    def bottleneck(states, config):
        if case == "normal":
            return []
        return [BottleneckEvent("R1", states[0].timestamp, 15, "HIGH", 75,
                                ["DCR_HIGH"], {"demand": 8, "capacity": 7})]
    def diagnose(*args):
        names = {"demand": ["DEMAND_SPIKE"], "amr": ["AMR_AVAILABILITY_DROP"],
                 "multi": ["DEMAND_SPIKE", "AMR_AVAILABILITY_DROP"]}[case]
        return [Cause(name, "high", {"test_evidence": True}) for name in names]
    def simulate(current, condition, scenario, seed):
        intervention = bool(scenario.actions)
        return SimulationResult(scenario.scenario_id, 2 if intervention else 5, 5,
            1 if intervention else 4, 4, 0, 110 if intervention else 100,
            99 if intervention else 95, 0, 0, 0, {"AMR01": .8},
            secondary and intervention)
    return {"forecast": Mock(side_effect=forecast), "future_state": Mock(side_effect=future),
            "bottleneck": Mock(side_effect=bottleneck), "diagnose": Mock(side_effect=diagnose),
            "simulate": Mock(side_effect=simulate)}


def test_normal_skips_diagnosis_and_simulation(config):
    deps = services("normal")
    result = _execute(config, services=deps)
    assert result.status == "No intervention required"
    assert result.decision_package is None
    assert result.scenarios[0].scenario_id == "S0"
    deps["diagnose"].assert_not_called()
    deps["simulate"].assert_not_called()


@pytest.mark.parametrize("case", ["demand", "amr", "multi"])
def test_bottleneck_integration(config, case):
    result = _execute(config, services=services(case))
    assert result.bottlenecks and result.decision_package
    assert result.scenarios[0].scenario_id == "S0"
    assert len(result.scenarios) <= 8
    if case == "amr":
        assert any(a.action_type == "REASSIGN_AMR" for s in result.scenarios for a in s.actions)
    if case == "multi":
        assert len(result.causes) == 2
        assert any(len(s.actions) == 2 for s in result.scenarios)
    assert result.decision_package.baseline_result.scenario_id == "S0"
    assert result.decision_package.recommended_scenario.scenario_id in result.robustness


def test_secondary_bottleneck_never_recommended(config):
    result = _execute(config, services=services("multi", secondary=True))
    assert result.decision_package.recommended_scenario.scenario_id == "S0"
    assert result.rejected_scenarios
    assert all("CRITICAL_SECONDARY_BOTTLENECK" in reasons for reasons in result.rejected_scenarios.values())


def test_seed_conditions_and_maintenance_preserved(config):
    deps = services("multi")
    result = _execute(config, seed=123, services=deps)
    calls = deps["simulate"].call_args_list
    assert {c.args[1]["quantile"] for c in calls} == {"p10", "p50", "p90"}
    expected_events = calls[0].args[1]["known_events"]
    for call in calls:
        assert call.kwargs["seed"] == 123
        assert call.args[1]["known_events"].equals(expected_events)
        if call.args[1]["condition"] == "adverse":
            assert call.args[1]["additional_amr_unavailable"] == 1
    assert "S0" in result.results_by_condition["adverse"]


def test_stage_failure_is_actionable(config):
    deps = services()
    deps["forecast"].side_effect = ValueError("Model unavailable")
    with pytest.raises(PipelineError, match="forecast.*Model unavailable"):
        _execute(config, services=deps)
    deps["simulate"].assert_not_called()


def test_invalid_forecast_is_rejected(config):
    deps = services()
    deps["forecast"].side_effect = None
    deps["forecast"].return_value = []
    with pytest.raises(PipelineError, match="timestamps"):
        _execute(config, services=deps)


def test_unknown_mode_is_rejected(config):
    with pytest.raises(PipelineError, match="Unknown decision mode"):
        _execute(config, decision_mode="unknown", services=services())


def test_invalid_simulation_identity_is_rejected(config):
    deps = services()
    original = deps["simulate"].side_effect
    deps["simulate"].side_effect = lambda *a, **kw: replace(original(*a, **kw), scenario_id="wrong")
    with pytest.raises(PipelineError, match="matching SimulationResult"):
        _execute(config, services=deps)


def test_public_pipeline_never_uses_mock_fallback(monkeypatch):
    import src.forecast.service as forecast_service
    monkeypatch.delattr(forecast_service, "forecast_future_drivers", raising=False)
    with pytest.raises(PipelineError, match="Missing upstream API.*forecast_future_drivers"):
        run_pipeline()
    assert any("forecast" in message for message in module_readiness())


def test_no_validation_labels_read(config, monkeypatch):
    import pandas as pd
    original = pd.read_csv
    reads = []
    def guarded(path, *args, **kwargs):
        reads.append(str(path))
        assert "validation_only" not in str(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(pd, "read_csv", guarded)
    _execute(config, services=services("multi"))
    assert reads


def test_persist_and_operator_audit(config):
    result = _execute(config, services=services())
    path = save_run(result, config)
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == result.run_id
    for decision in ("APPROVE", "MODIFY", "REJECT"):
        audit = record_operator_decision(result, decision, "=unsafe note", config)
    with audit.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["decision"] for r in rows] == ["APPROVE", "MODIFY", "REJECT"]
    assert rows[0]["notes"] == "'=unsafe note"
    with pytest.raises(ValueError, match="modification"):
        record_operator_decision(result, "MODIFY", config=config)
    with pytest.raises(ValueError, match="Unknown"):
        record_operator_decision(result, "other", config=config)
    normal = _execute(config, services=services("normal"))
    with pytest.raises(ValueError, match="No recommendation"):
        record_operator_decision(normal, "APPROVE", config=config)


def test_config_missing_and_forbidden_paths(tmp_path):
    import shutil
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "config", tmp_path / "config")
    path = tmp_path / "config/system.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    del raw["seed"]
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="seed"):
        load_config(tmp_path)
    raw["seed"] = 42
    raw["paths"]["current_state"] = "data/validation_only/labels.csv"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="Forbidden"):
        load_config(tmp_path)


def test_config_from_other_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config["paths"]["current_state"].is_file()
    assert config["readiness_warnings"]  # current upstream thresholds are empty


def test_critical_bottleneck_precedes_higher_risk(config):
    deps = services()
    original = deps["bottleneck"].side_effect
    def detect(*args):
        high = original(*args)[0]
        return [high, replace(high, severity="Critical", risk_score=40, location="R2")]
    deps["bottleneck"].side_effect = detect
    result = _execute(config, services=deps)
    assert result.decision_package.bottleneck.severity == "Critical"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_kpi_is_rejected(config, value):
    deps = services()
    original = deps["simulate"].side_effect
    deps["simulate"].side_effect = lambda *a, **kw: replace(original(*a, **kw), throughput=value)
    with pytest.raises(PipelineError, match="Invalid numeric simulation"):
        _execute(config, services=deps)


@pytest.mark.parametrize("page", ["Home.py", "pages/1_Control_Tower.py",
    "pages/2_Bottleneck_Cause.py", "pages/3_Scenario_Comparison.py", "pages/4_Recommendation.py"])
def test_dashboard_pages_render_with_test_run(config, page):
    from streamlit.testing.v1 import AppTest
    result = _execute(config, services=services("multi"))
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app" / page), default_timeout=20)
    app.session_state["pipeline_result"] = result
    app.run()
    assert not app.exception


def test_dashboard_missing_modules_is_visible():
    from streamlit.testing.v1 import AppTest
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app/Home.py"), default_timeout=20).run()
    assert not app.exception
    assert any("forecast" in warning.value for warning in app.warning)
    next(button for button in app.button if button.label == "Run Decision Twin").click().run()
    assert not app.exception
    assert any("Chưa thể chạy pipeline thật" in error.value for error in app.error)
    assert "pipeline_result" not in app.session_state


def test_dashboard_operator_buttons_write_audit(config, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import app.Home as home
    monkeypatch.setattr(home, "load_config", lambda: config)
    result = _execute(config, services=services())
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app/pages/4_Recommendation.py"), default_timeout=20)
    app.session_state["pipeline_result"] = result
    app.run()
    next(button for button in app.button if button.label == "MODIFY").click().run()
    assert any("modification" in error.value for error in app.error)
    next(button for button in app.button if button.label == "APPROVE").click().run()
    assert not app.exception
    path = config["paths"]["artifacts_dir"] / "operator_decisions.csv"
    assert path.is_file()
    with path.open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle))[0]["decision"] == "APPROVE"
    next(button for button in app.button if button.label == "RUN AGAIN").click().run()
    assert "pipeline_result" not in app.session_state
