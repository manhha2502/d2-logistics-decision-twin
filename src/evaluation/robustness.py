from pathlib import Path
from typing import Any
import yaml
import numpy as np

from src.common.schemas import Scenario, SimulationResult

DEFAULT_DECISION_CONFIG = Path("config/decision_modes.yaml")


def load_decision_modes_config(config_path: Path | str = DEFAULT_DECISION_CONFIG) -> dict[str, Any]:
    """Tải cấu hình decision modes từ YAML."""
    path = Path(config_path)
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("decision_modes", {})


def calculate_scenario_score(
    scenario: Scenario,
    sim_result: SimulationResult,
    mode_weights: dict[str, float],
    min_max_bounds: dict[str, tuple[float, float]],
) -> float:
    """
    Tính điểm tổng hợp (composite score) của một kịch bản theo trọng số của Decision Mode:
    Chuẩn hóa các chỉ số về thang [0, 1]:
    - Càng lớn càng tốt: (val - min) / (max - min + eps)
    - Càng nhỏ càng tốt: (max - val) / (max - min + eps)
    """
    eps = 1e-6

    def norm_high(val: float, bounds: tuple[float, float]) -> float:
        b_min, b_max = bounds
        if b_max - b_min < eps:
            return 1.0
        return float(np.clip((val - b_min) / (b_max - b_min + eps), 0.0, 1.0))

    def norm_low(val: float, bounds: tuple[float, float]) -> float:
        b_min, b_max = bounds
        if b_max - b_min < eps:
            return 1.0
        return float(np.clip((b_max - val) / (b_max - b_min + eps), 0.0, 1.0))

    # Chuẩn hóa từng metric
    score_srv = norm_high(sim_result.service_level, min_max_bounds["service_level"])
    score_tp = norm_high(sim_result.throughput, min_max_bounds["throughput"])
    score_wait = norm_low(sim_result.avg_waiting_time, min_max_bounds["waiting_time"])
    score_queue = norm_low(sim_result.avg_queue, min_max_bounds["queue"])
    score_late = norm_low(float(sim_result.late_delivery_count), min_max_bounds["late_delivery"])
    score_disrupt = norm_low(scenario.estimated_disruption, min_max_bounds["disruption"])

    total_score = (
        mode_weights.get("service_level", 0.0) * score_srv
        + mode_weights.get("throughput", 0.0) * score_tp
        + mode_weights.get("waiting_time", 0.0) * score_wait
        + mode_weights.get("queue_reduction", 0.0) * score_queue
        + mode_weights.get("late_delivery", 0.0) * score_late
        + mode_weights.get("disruption", 0.0) * score_disrupt
    )
    return float(total_score)


def rank_scenarios(
    scenarios: list[Scenario],
    sim_results: dict[str, SimulationResult],
    decision_mode: str = "balanced",
    config_path: Path | str = DEFAULT_DECISION_CONFIG,
) -> list[tuple[Scenario, float]]:
    """
    Xếp hạng các kịch bản theo Decision Mode:
    - Trọng số chỉ được áp dụng sau khi đã qua dynamic constraints & lọc Pareto.
    - Trả về danh sách (Scenario, score) sắp xếp giảm dần theo điểm.
    """
    modes_cfg = load_decision_modes_config(config_path)
    mode_info = modes_cfg.get(decision_mode, modes_cfg.get("balanced", {}))
    weights = mode_info.get("weights", {})

    valid_scenarios = [s for s in scenarios if s.scenario_id in sim_results]
    if not valid_scenarios:
        return []

    # Thu thập min / max bounds cho việc chuẩn hóa
    all_srv = [sim_results[s.scenario_id].service_level for s in valid_scenarios]
    all_tp = [sim_results[s.scenario_id].throughput for s in valid_scenarios]
    all_wait = [sim_results[s.scenario_id].avg_waiting_time for s in valid_scenarios]
    all_queue = [sim_results[s.scenario_id].avg_queue for s in valid_scenarios]
    all_late = [float(sim_results[s.scenario_id].late_delivery_count) for s in valid_scenarios]
    all_disrupt = [s.estimated_disruption for s in valid_scenarios]

    bounds = {
        "service_level": (min(all_srv), max(all_srv)),
        "throughput": (min(all_tp), max(all_tp)),
        "waiting_time": (min(all_wait), max(all_wait)),
        "queue": (min(all_queue), max(all_queue)),
        "late_delivery": (min(all_late), max(all_late)),
        "disruption": (min(all_disrupt), max(all_disrupt)),
    }

    scored: list[tuple[Scenario, float]] = []
    for sc in valid_scenarios:
        res = sim_results[sc.scenario_id]
        score = calculate_scenario_score(sc, res, weights, bounds)
        scored.append((sc, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def evaluate_robustness(
    top_scenarios: list[Scenario],
    sim_results_by_condition: dict[str, dict[str, SimulationResult]],
    decision_mode: str = "balanced",
    config_path: Path | str = DEFAULT_DECISION_CONFIG,
) -> dict[str, Any]:
    """
    Đánh giá độ bền (Robustness) của top kịch bản dưới 3 điều kiện:
    - favorable (P10)
    - expected (P50)
    - adverse (P90)
    """
    robustness_summary: dict[str, Any] = {}

    for sc in top_scenarios:
        sc_id = sc.scenario_id
        res_exp = sim_results_by_condition.get("expected", {}).get(sc_id)
        res_fav = sim_results_by_condition.get("favorable", {}).get(sc_id)
        res_adv = sim_results_by_condition.get("adverse", {}).get(sc_id)

        srv_exp = res_exp.service_level if res_exp else 0.0
        srv_fav = res_fav.service_level if res_fav else srv_exp
        srv_adv = res_adv.service_level if res_adv else srv_exp

        # Độ suy giảm chất lượng dịch vụ ở điều kiện bất lợi nhất (Adverse Drop)
        drop_pct = ((srv_exp - srv_adv) / (srv_exp + 1e-6)) * 100.0

        if drop_pct <= 5.0:
            rating = "ROBUST"
        elif drop_pct <= 15.0:
            rating = "MODERATE"
        else:
            rating = "SENSITIVE"

        robustness_summary[sc_id] = {
            "expected_service_level": float(srv_exp),
            "favorable_service_level": float(srv_fav),
            "adverse_service_level": float(srv_adv),
            "adverse_drop_pct": float(drop_pct),
            "rating": rating,
        }

    return robustness_summary
