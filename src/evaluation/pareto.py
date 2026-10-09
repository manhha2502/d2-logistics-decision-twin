from src.common.schemas import Scenario, SimulationResult


def dominates(
    sc_a: Scenario,
    res_a: SimulationResult,
    sc_b: Scenario,
    res_b: SimulationResult,
) -> bool:
    """
    Kiểm tra xem phương án A có trội hơn (dominate) phương án B không.
    A dominate B khi:
    - Ở mọi tiêu chí, A tốt hơn hoặc bằng B.
    - Ở ít nhất một tiêu chí, A tốt hơn hẳn B.

    Tiêu chí (Higher is better):
    - service_level
    - throughput

    Tiêu chí (Lower is better):
    - avg_waiting_time
    - avg_queue
    - late_delivery_count
    - estimated_disruption
    """
    # 1. Higher is better
    higher_better_a = [res_a.service_level, res_a.throughput]
    higher_better_b = [res_b.service_level, res_b.throughput]

    # 2. Lower is better
    lower_better_a = [
        res_a.avg_waiting_time,
        res_a.avg_queue,
        float(res_a.late_delivery_count),
        sc_a.estimated_disruption,
    ]
    lower_better_b = [
        res_b.avg_waiting_time,
        res_b.avg_queue,
        float(res_b.late_delivery_count),
        sc_b.estimated_disruption,
    ]

    # Kiểm tra: A không được tệ hơn B ở bất kỳ tiêu chí nào
    no_worse = True
    for val_a, val_b in zip(higher_better_a, higher_better_b):
        if val_a < val_b:
            no_worse = False
            break

    if no_worse:
        for val_a, val_b in zip(lower_better_a, lower_better_b):
            if val_a > val_b:
                no_worse = False
                break

    if not no_worse:
        return False

    # Kiểm tra: A phải tốt hơn hẳn B ở ít nhất 1 tiêu chí
    strictly_better = False
    for val_a, val_b in zip(higher_better_a, higher_better_b):
        if val_a > val_b:
            strictly_better = True
            break

    if not strictly_better:
        for val_a, val_b in zip(lower_better_a, lower_better_b):
            if val_a < val_b:
                strictly_better = True
                break

    return strictly_better


def filter_pareto_front(
    scenarios: list[Scenario],
    sim_results: dict[str, SimulationResult],
) -> list[Scenario]:
    """
    Lọc và chỉ giữ lại các Scenario thuộc Pareto Front (không bị dominate bởi scenario nào khác).
    Thuật toán Non-dominated Sorting đơn giản (O(N^2)).
    """
    valid_scenarios = [s for s in scenarios if s.scenario_id in sim_results]
    n = len(valid_scenarios)
    if n <= 1:
        return valid_scenarios

    pareto_front: list[Scenario] = []

    for i in range(n):
        sc_i = valid_scenarios[i]
        res_i = sim_results[sc_i.scenario_id]
        is_dominated = False

        for j in range(n):
            if i == j:
                continue
            sc_j = valid_scenarios[j]
            res_j = sim_results[sc_j.scenario_id]

            if dominates(sc_j, res_j, sc_i, res_i):
                is_dominated = True
                break

        if not is_dominated:
            pareto_front.append(sc_i)

    return pareto_front
