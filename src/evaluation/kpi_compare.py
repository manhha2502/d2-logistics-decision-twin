from typing import Any
from src.common.schemas import Scenario, SimulationResult

EPSILON = 1e-6


def compare_kpi_vs_baseline(
    scenario_result: SimulationResult,
    baseline_result: SimulationResult,
    scenario: Scenario | None = None,
) -> dict[str, float]:
    """
    So sánh các chỉ số KPI của một Scenario với Baseline S0:
    - Lower is better: waiting_time, queue, late_delivery, starvation, unmet_consumption.
      % cải thiện = (Baseline - Scenario) / (Baseline + EPSILON) * 100
      (Giá trị dương nghĩa là Scenario tốt hơn Baseline).
    - Higher is better: throughput, service_level.
      % cải thiện = (Scenario - Baseline) / (Baseline + EPSILON) * 100
      (Giá trị dương nghĩa là Scenario tốt hơn Baseline).
    """
    # Lower is better:
    waiting_improve = (
        (baseline_result.avg_waiting_time - scenario_result.avg_waiting_time)
        / (baseline_result.avg_waiting_time + EPSILON)
    ) * 100.0

    queue_improve = (
        (baseline_result.avg_queue - scenario_result.avg_queue)
        / (baseline_result.avg_queue + EPSILON)
    ) * 100.0

    late_improve = (
        (baseline_result.late_delivery_count - scenario_result.late_delivery_count)
        / (baseline_result.late_delivery_count + EPSILON)
    ) * 100.0

    starvation_improve = (
        (baseline_result.starvation_minutes - scenario_result.starvation_minutes)
        / (baseline_result.starvation_minutes + EPSILON)
    ) * 100.0

    unmet_improve = (
        (baseline_result.unmet_consumption - scenario_result.unmet_consumption)
        / (baseline_result.unmet_consumption + EPSILON)
    ) * 100.0

    # Higher is better:
    throughput_improve = (
        (scenario_result.throughput - baseline_result.throughput)
        / (baseline_result.throughput + EPSILON)
    ) * 100.0

    service_level_improve = (
        (scenario_result.service_level - baseline_result.service_level)
        / (baseline_result.service_level + EPSILON)
    ) * 100.0

    disruption = scenario.estimated_disruption if scenario else 0.0

    return {
        "waiting_time_pct": float(waiting_improve),
        "queue_reduction_pct": float(queue_improve),
        "late_delivery_reduction_pct": float(late_improve),
        "starvation_reduction_pct": float(starvation_improve),
        "unmet_consumption_reduction_pct": float(unmet_improve),
        "throughput_pct": float(throughput_improve),
        "service_level_pct": float(service_level_improve),
        "disruption": float(disruption),
    }


def compare_all_scenarios(
    scenarios: list[Scenario],
    sim_results: dict[str, SimulationResult],
) -> dict[str, dict[str, float]]:
    """So sánh tất cả scenarios với S0."""
    baseline = sim_results.get("S0")
    if not baseline:
        raise ValueError("Thiếu SimulationResult của kịch bản cơ sở S0!")

    results_map: dict[str, dict[str, float]] = {}
    sc_dict = {sc.scenario_id: sc for sc in scenarios}

    for sc_id, sim_res in sim_results.items():
        sc = sc_dict.get(sc_id)
        results_map[sc_id] = compare_kpi_vs_baseline(sim_res, baseline, sc)

    return results_map
