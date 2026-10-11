"""Acceptance checks using the real PEAK v2 data and all production modules."""

from pathlib import Path
from copy import deepcopy

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.common.config import load_config
from src.forecast import service as forecast_service
from src.orchestration.pipeline import _execute, run_pipeline


def test_default_snapshot_runs_end_to_end_without_mocks():
    result = run_pipeline()
    assert len(result.forecasts) == 4
    assert len(result.future_states) == 8
    assert result.bottlenecks
    assert {cause.cause_type for cause in result.causes} >= {"AMR_AVAILABILITY_DROP"}
    assert result.scenarios[0].scenario_id == "S0"
    assert any(action.action_type == "REASSIGN_AMR"
               for scenario in result.scenarios for action in scenario.actions)
    assert set(result.simulation_results) == {scenario.scenario_id for scenario in result.scenarios}
    assert set(result.results_by_condition) == {"expected", "favorable", "adverse"}
    assert result.decision_package is not None
    assert result.decision_package.recommended_scenario.scenario_id == "S1"
    assert result.simulation_results["S1"].throughput > result.simulation_results["S0"].throughput
    assert not result.simulation_results["S1"].secondary_bottleneck
    assert result.decision_package.side_effects["warnings"]


def test_dashboard_run_button_uses_real_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr("src.orchestration.pipeline.save_run",
                        lambda result, config: tmp_path / f"{result.run_id}.json")
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "app/Home.py"), default_timeout=30).run()
    next(button for button in app.button if button.label == "Run Decision Twin").click().run()
    assert not app.exception
    assert not app.error
    result = app.session_state["pipeline_result"]
    assert result.status == "Recommendation ready"
    assert result.decision_package.recommended_scenario.scenario_id == "S1"


def test_normal_inputs_skip_simpy_with_real_modules(monkeypatch, tmp_path):
    config = deepcopy(load_config())
    current = pd.read_csv(config["paths"]["current_state"])
    current.loc[(current.entity_type == "RESOURCE") & (current.entity_id == "AMR04")
                & (current.metric == "route_id"), "value"] = "R1"
    current.loc[(current.entity_type == "ROUTE") & (current.entity_id == "R1")
                & (current.metric == "queue_end_totes"), "value"] = "0"
    events = pd.read_csv(config["paths"]["known_events"]).iloc[:0]
    current_path, events_path = tmp_path / "current.csv", tmp_path / "events.csv"
    current.to_csv(current_path, index=False)
    events.to_csv(events_path, index=False)
    config["paths"].update(current_state=current_path, known_events=events_path)
    monkeypatch.setattr(forecast_service, "load_config", lambda: config)
    result = _execute(config)
    assert result.status == "No intervention required"
    assert not result.bottlenecks
    assert not result.simulation_results


def test_multi_cause_inputs_generate_combined_scenarios_with_real_modules(monkeypatch, tmp_path):
    config = deepcopy(load_config())
    current = pd.read_csv(config["paths"]["current_state"])
    current.loc[(current.entity_type == "BUFFER") & (current.entity_id == "MAT_A")
                & (current.metric == "current_level_totes"), "value"] = "1"
    current_path = tmp_path / "current.csv"
    current.to_csv(current_path, index=False)
    config["paths"]["current_state"] = current_path
    monkeypatch.setattr(forecast_service, "load_config", lambda: config)
    result = _execute(config)
    assert {cause.cause_type for cause in result.causes} >= {
        "AMR_AVAILABILITY_DROP", "BUFFER_LOW"}
    assert any(len(scenario.actions) == 2 for scenario in result.scenarios)
    assert result.simulation_results


def test_r2_peak_rejects_reassignment_with_real_simpy():
    config = deepcopy(load_config())
    # Synthetic stress input for the auxiliary pool; all outcomes still come
    # from the real forecast, state engine, SimPy, and decision modules.
    config["system"]["simulation"]["calibrate_from_history"] = False
    config["system"]["simulation"]["baseline_demand_r2"] = 7.0
    result = _execute(config)
    assert result.simulation_results["S1"].secondary_bottleneck
    assert "CRITICAL_SECONDARY_BOTTLENECK" in result.rejected_scenarios["S1"]
    assert result.decision_package.recommended_scenario.scenario_id == "S0"
