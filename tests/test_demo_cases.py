"""Five acceptance scenarios required by the implementation plan."""

from pathlib import Path

import yaml

from scripts.demo_cases import run_case


def test_all_plan_demo_cases_use_real_pipeline(tmp_path):
    root = Path(__file__).resolve().parents[1]
    settings = yaml.safe_load((root / "config/demo_cases.yaml").read_text(encoding="utf-8"))["cases"]
    results = {name: run_case(name, inputs, tmp_path) for name, inputs in settings.items()}

    normal = results["normal"]
    assert normal.status == "No intervention required"
    assert not normal.simulation_results

    demand = results["demand_spike"]
    assert demand.bottlenecks
    assert "DEMAND_SPIKE" in {cause.cause_type for cause in demand.causes}
    assert any(scenario.actions for scenario in demand.scenarios)
    assert demand.simulation_results

    failure = results["amr_failure"]
    assert any(action.action_type == "REASSIGN_AMR"
               for scenario in failure.scenarios for action in scenario.actions)
    assert failure.decision_package is not None

    multi = results["multi_cause"]
    assert len({cause.cause_type for cause in multi.causes}) > 1
    assert any(len(scenario.actions) == 2 for scenario in multi.scenarios)

    secondary = results["secondary_bottleneck"]
    assert secondary.simulation_results["S1"].secondary_bottleneck
    assert "CRITICAL_SECONDARY_BOTTLENECK" in secondary.rejected_scenarios["S1"]
    assert secondary.decision_package.recommended_scenario.scenario_id == "S0"
