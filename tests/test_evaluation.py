import pytest
from src.common.schemas import Scenario, SimulationResult, Action
from src.evaluation.constraints import (
    apply_dynamic_constraints,
    check_dynamic_constraints,
)
from src.evaluation.kpi_compare import compare_kpi_vs_baseline
from src.evaluation.pareto import filter_pareto_front, dominates
from src.evaluation.robustness import rank_scenarios, evaluate_robustness


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


def test_secondary_bottleneck_rejected_by_dynamic_constraints():
    """Test 6: Kịch bản gây secondary bottleneck trên R2 phải bị dynamic filter loại bỏ."""
    sc_bad = Scenario(scenario_id="S1", actions=[], cause_coverage=[])
    res_bad = create_mock_sim_result("S1", secondary_bottleneck=True)

    passed, reasons = check_dynamic_constraints(res_bad)
    assert not passed
    assert "CRITICAL_SECONDARY_BOTTLENECK" in reasons

    scenarios = [Scenario(scenario_id="S0", actions=[], cause_coverage=[]), sc_bad]
    sim_results = {
        "S0": create_mock_sim_result("S0"),
        "S1": res_bad,
    }
    valid_scs, rejected = apply_dynamic_constraints(scenarios, sim_results)
    assert any(s.scenario_id == "S0" for s in valid_scs)
    assert not any(s.scenario_id == "S1" for s in valid_scs)
    assert "S1" in rejected


def test_pareto_filtering_removes_dominated_scenario():
    """Test 7: Thuật toán Pareto loại bỏ kịch bản bị dominated chính xác."""
    # S1 tốt hơn S2 ở mọi mặt: waiting thấp hơn, throughput cao hơn, service cao hơn, disruption thấp hơn
    sc1 = Scenario(scenario_id="S1", actions=[], cause_coverage=[], estimated_disruption=1.0)
    res1 = create_mock_sim_result("S1", waiting=2.0, queue=1.0, late=0, tp=120.0, service=98.0)

    sc2 = Scenario(scenario_id="S2", actions=[], cause_coverage=[], estimated_disruption=3.0)
    res2 = create_mock_sim_result("S2", waiting=5.0, queue=3.0, late=2, tp=100.0, service=90.0)

    assert dominates(sc1, res1, sc2, res2)
    assert not dominates(sc2, res2, sc1, res1)

    pareto_scs = filter_pareto_front([sc1, sc2], {"S1": res1, "S2": res2})
    assert len(pareto_scs) == 1
    assert pareto_scs[0].scenario_id == "S1"


def test_decision_modes_produce_different_rankings():
    """Test 8: Các Decision Mode khác nhau có thể đưa ra thứ tự xếp hạng khác nhau."""
    # S1: Service level cực cao, nhưng disruption cao
    sc1 = Scenario(scenario_id="S1", actions=[], cause_coverage=[], estimated_disruption=4.0)
    res1 = create_mock_sim_result("S1", waiting=1.0, tp=150.0, service=99.0)

    # S2: Disruption cực thấp (ít can thiệp), service level trung bình
    sc2 = Scenario(scenario_id="S2", actions=[], cause_coverage=[], estimated_disruption=0.5)
    res2 = create_mock_sim_result("S2", waiting=3.0, tp=110.0, service=92.0)

    scenarios = [sc1, sc2]
    sim_results = {"S1": res1, "S2": res2}

    # service_priority mode -> S1 phải xếp trên S2
    ranked_service = rank_scenarios(scenarios, sim_results, decision_mode="service_priority")
    assert ranked_service[0][0].scenario_id == "S1"

    # low_disruption mode -> S2 phải xếp trên S1
    ranked_disrupt = rank_scenarios(scenarios, sim_results, decision_mode="low_disruption")
    assert ranked_disrupt[0][0].scenario_id == "S2"


def test_kpi_comparison_vs_baseline():
    """Kiểm tra tính toán % cải thiện KPI so với Baseline S0."""
    res_s0 = create_mock_sim_result("S0", waiting=10.0, tp=100.0, service=80.0)
    res_s1 = create_mock_sim_result("S1", waiting=5.0, tp=120.0, service=96.0)

    comp = compare_kpi_vs_baseline(res_s1, res_s0)
    # waiting time giảm từ 10 xuống 5 -> cải thiện 50%
    assert comp["waiting_time_pct"] == pytest.approx(50.0, rel=1e-2)
    # throughput tăng từ 100 lên 120 -> cải thiện 20%
    assert comp["throughput_pct"] == pytest.approx(20.0, rel=1e-2)
    # service level tăng từ 80 lên 96 -> cải thiện 20%
    assert comp["service_level_pct"] == pytest.approx(20.0, rel=1e-2)
