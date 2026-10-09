from pathlib import Path
from typing import Any

from src.common.schemas import (
    BottleneckEvent,
    Cause,
    DecisionPackage,
    Scenario,
    SimulationResult,
)
from src.evaluation.constraints import apply_dynamic_constraints
from src.evaluation.kpi_compare import compare_kpi_vs_baseline
from src.evaluation.pareto import filter_pareto_front
from src.evaluation.robustness import rank_scenarios, evaluate_robustness


def build_decision_package(
    bottleneck: BottleneckEvent,
    causes: list[Cause],
    scenarios: list[Scenario],
    sim_results: dict[str, SimulationResult],
    decision_mode: str = "balanced",
    sim_results_by_condition: dict[str, dict[str, SimulationResult]] | None = None,
    config_path: Path | str = "config/decision_modes.yaml",
) -> DecisionPackage:
    """
    Xây dựng gói quyết định (DecisionPackage) hoàn chỉnh:
    1. Kiểm tra baseline S0.
    2. Lọc dynamic constraints (loại kịch bản gây starvation, buffer overflow, secondary bottleneck).
    3. Lọc tập Pareto Front (loại kịch bản bị dominate).
    4. Xếp hạng theo trọng số của Decision Mode (balanced / service_priority / low_disruption).
    5. Chọn phương án tối ưu nhất.
    6. Tính toán % cải thiện KPI so với S0.
    7. Đánh giá độ bền (Robustness) và cảnh báo tác dụng phụ (Side effects).
    """
    # 1. Kiểm tra baseline S0
    baseline_res = sim_results.get("S0")
    if not baseline_res:
        raise ValueError("Bắt buộc phải có kết quả mô phỏng của kịch bản cơ sở S0!")

    s0_scenario = next((s for s in scenarios if s.scenario_id == "S0"), None)
    if not s0_scenario:
        s0_scenario = Scenario(scenario_id="S0", actions=[], cause_coverage=[])

    # 2. Lọc dynamic constraints
    valid_scenarios, rejected_info = apply_dynamic_constraints(
        scenarios, sim_results, config_path=config_path
    )

    # 3. Lọc Pareto Front
    pareto_scenarios = filter_pareto_front(valid_scenarios, sim_results)

    # 4. Xếp hạng theo Decision Mode
    ranked = rank_scenarios(
        pareto_scenarios, sim_results, decision_mode=decision_mode, config_path=config_path
    )

    # 5. Chọn kịch bản khuyến nghị tốt nhất
    recommended_sc: Scenario
    # Ưu tiên kịch bản can thiệp có điểm cao nhất (nếu có và tốt hơn S0)
    non_s0_ranked = [item for item in ranked if item[0].scenario_id != "S0"]
    if non_s0_ranked:
        recommended_sc = non_s0_ranked[0][0]
    else:
        # Nếu không có kịch bản nào khả thi hoặc tốt hơn, khuyến nghị S0 (No Action)
        recommended_sc = s0_scenario

    recommended_res = sim_results[recommended_sc.scenario_id]

    # 6. Tính toán cải thiện KPI vs S0
    kpi_imp = compare_kpi_vs_baseline(recommended_res, baseline_res, recommended_sc)

    # 7. Robustness
    if sim_results_by_condition:
        rob_summary = evaluate_robustness(
            [recommended_sc],
            sim_results_by_condition,
            decision_mode=decision_mode,
            config_path=config_path,
        )
    else:
        # Nếu chỉ có kết quả expected (P50)
        rob_summary = {
            recommended_sc.scenario_id: {
                "expected_service_level": recommended_res.service_level,
                "rating": "UNTESTED_MULTI_CONDITION",
            }
        }

    # 8. Side effects & Cảnh báo rủi ro
    side_effects: dict[str, Any] = {
        "rejected_scenarios_count": len(rejected_info),
        "rejected_reasons": rejected_info,
        "amr_reassigned": False,
        "warnings": [],
    }

    # Ghi nhận thông tin timing (start/duration) của các action được đề xuất
    side_effects["execution_timing"] = [
        {
            "action_id": act.action_id,
            "action_type": act.action_type,
            "start_time": act.parameters.get("start_time", "NOW"),
            "duration_min": act.parameters.get("duration_min", 45),
        }
        for act in recommended_sc.actions
    ]

    # Kiểm tra xem có điều chuyển AMR không
    for act in recommended_sc.actions:
        if act.action_type == "REASSIGN_AMR":
            side_effects["amr_reassigned"] = True
            from_r = act.parameters.get("from_route", "R2")
            count = act.parameters.get("count", 1)
            side_effects["warnings"].append(
                f"Tạm thời mượn {count} AMR từ tuyến {from_r}. Cần theo dõi dung lượng và hàng đợi của tuyến {from_r}."
            )

    return DecisionPackage(
        bottleneck=bottleneck,
        causes=causes,
        recommended_scenario=recommended_sc,
        baseline_result=baseline_res,
        recommended_result=recommended_res,
        kpi_improvement=kpi_imp,
        robustness=rob_summary,
        side_effects=side_effects,
    )
