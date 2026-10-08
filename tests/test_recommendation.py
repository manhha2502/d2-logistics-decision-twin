from datetime import datetime
import pytest

from src.common.schemas import (
    BottleneckEvent,
    Cause,
    DecisionPackage,
    Scenario,
    SimulationResult,
)
from src.actions.scenario_generator import generate_scenarios
from src.recommendation.builder import build_decision_package


def create_mock_sim_result(
    scenario_id: str,
    waiting: float = 5.0,
    queue: float = 3.0,
    late: int = 0,
    tp: float = 100.0,
    service: float = 95.0,
    starvation: float = 0.0,
    unmet: float = 0.0,
    overflow: float = 0.0,
    secondary_bottleneck: bool = False,
) -> SimulationResult:
    return SimulationResult(
        scenario_id=scenario_id,
        avg_waiting_time=waiting,
        max_waiting_time=waiting * 1.5,
        avg_queue=queue,
        max_queue=queue * 1.5,
        late_delivery_count=late,
        throughput=tp,
        service_level=service,
        starvation_minutes=starvation,
        unmet_consumption=unmet,
        buffer_overflow=overflow,
        amr_utilization={"AMR01": 0.8},
        secondary_bottleneck=secondary_bottleneck,
    )


def test_full_pipeline_end_to_end():
    """
    Test trọn vẹn luồng từ:
    Cause -> Actions -> Scenarios -> Feasibility -> Constraints -> Pareto -> Robustness -> DecisionPackage
    """
    # 1. Mock Bottleneck & Causes (từ Hà)
    bottleneck = BottleneckEvent(
        location="R1",
        predicted_time=datetime(2026, 10, 8, 14, 30),
        lead_time_min=30,
        severity="HIGH",
        risk_score=78.5,
        triggered_rules=["DCR_HIGH", "QUEUE_GROWTH"],
        evidence={"dcr": 1.25, "queue_totes": 8.0},
    )

    causes = [
        Cause(
            cause_type="DEMAND_SPIKE",
            contribution="high",
            evidence={"forecast_demand_increase_pct": 35.0},
        ),
        Cause(
            cause_type="AMR_AVAILABILITY_DROP",
            contribution="medium",
            evidence={"available_amr": 2},
        ),
    ]

    # 2. Sinh Scenarios & kiểm tra static feasibility (Quân)
    scenarios = generate_scenarios(causes, max_scenarios=6)
    assert len(scenarios) >= 2
    assert scenarios[0].scenario_id == "S0"

    # 3. Mock Simulation Results (từ Phú) cho từng scenario
    sim_results: dict[str, SimulationResult] = {}
    for sc in scenarios:
        if sc.scenario_id == "S0":
            sim_results["S0"] = create_mock_sim_result(
                "S0", waiting=8.0, queue=5.0, late=3, tp=90.0, service=82.0
            )
        else:
            # Các scenario can thiệp cải thiện tình trạng
            sim_results[sc.scenario_id] = create_mock_sim_result(
                sc.scenario_id, waiting=3.0, queue=1.5, late=0, tp=115.0, service=98.0
            )

    # 4. Mock Multi-condition simulation cho Robustness
    sim_by_condition = {
        "expected": sim_results,
        "favorable": {
            sc_id: create_mock_sim_result(sc_id, service=99.0) for sc_id in sim_results
        },
        "adverse": {
            sc_id: create_mock_sim_result(sc_id, service=92.0) for sc_id in sim_results
        },
    }

    # 5. Xây dựng Decision Package
    decision_pkg = build_decision_package(
        bottleneck=bottleneck,
        causes=causes,
        scenarios=scenarios,
        sim_results=sim_results,
        decision_mode="balanced",
        sim_results_by_condition=sim_by_condition,
    )

    # 6. Kiểm tra các trường bắt buộc của DecisionPackage
    assert isinstance(decision_pkg, DecisionPackage)
    # Where, When, Severity
    assert decision_pkg.bottleneck.location == "R1"
    assert decision_pkg.bottleneck.predicted_time is not None
    assert decision_pkg.bottleneck.severity == "HIGH"

    # Causes + evidence
    assert len(decision_pkg.causes) == 2
    for c in decision_pkg.causes:
        assert c.cause_type is not None
        assert isinstance(c.evidence, dict)

    # Recommended scenario, actions, start & duration
    assert decision_pkg.recommended_scenario.scenario_id != "S0"
    assert len(decision_pkg.recommended_scenario.actions) > 0
    for act in decision_pkg.recommended_scenario.actions:
        assert "start_time" in act.parameters
        assert "duration_min" in act.parameters

    # Baseline S0 KPI vs Recommended KPI
    assert decision_pkg.baseline_result.scenario_id == "S0"
    assert decision_pkg.recommended_result.scenario_id == decision_pkg.recommended_scenario.scenario_id

    # KPI improvements phải có giá trị dương (tốt hơn S0)
    assert decision_pkg.kpi_improvement["service_level_pct"] > 0
    assert decision_pkg.kpi_improvement["waiting_time_pct"] > 0
    assert decision_pkg.kpi_improvement["throughput_pct"] > 0

    # Side effects
    assert isinstance(decision_pkg.side_effects, dict)
    assert "execution_timing" in decision_pkg.side_effects

    # Robustness rating phải được tính toán
    rec_id = decision_pkg.recommended_scenario.scenario_id
    assert rec_id in decision_pkg.robustness
    assert "rating" in decision_pkg.robustness[rec_id]


def test_fallback_to_s0_when_all_interventions_rejected():
    """Nếu tất cả các kịch bản can thiệp đều vi phạm dynamic constraints thì fallback về S0."""
    bottleneck = BottleneckEvent(
        location="R1",
        predicted_time=datetime(2026, 10, 8, 14, 30),
        lead_time_min=30,
        severity="MEDIUM",
        risk_score=50.0,
        triggered_rules=[],
        evidence={},
    )
    causes = [Cause(cause_type="DEMAND_SPIKE", contribution="high", evidence={})]

    scenarios = [
        Scenario(scenario_id="S0", actions=[], cause_coverage=[]),
        Scenario(scenario_id="S1", actions=[], cause_coverage=[]),
    ]

    # S1 bị secondary bottleneck nên sẽ bị reject
    sim_results = {
        "S0": create_mock_sim_result("S0", service=80.0),
        "S1": create_mock_sim_result("S1", secondary_bottleneck=True, service=95.0),
    }

    decision_pkg = build_decision_package(
        bottleneck=bottleneck,
        causes=causes,
        scenarios=scenarios,
        sim_results=sim_results,
        decision_mode="balanced",
    )

    # Fallback về S0
    assert decision_pkg.recommended_scenario.scenario_id == "S0"
    assert decision_pkg.recommended_result.scenario_id == "S0"
