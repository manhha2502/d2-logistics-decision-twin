from itertools import combinations
from pathlib import Path
import pandas as pd

from src.actions.feasibility import check_static_feasibility
from src.actions.library import (
    get_action_disruption,
    get_candidate_actions,
    load_action_config,
)
from src.common.schemas import Action, Cause, Scenario


def calculate_cause_coverage(actions: list[Action], causes: list[Cause], actions_cfg: dict) -> list[str]:
    """Xác định danh sách các Cause mà tập action này giải quyết được."""
    input_cause_types = {c.cause_type for c in causes}
    covered: set[str] = set()
    for act in actions:
        addressed = set(actions_cfg.get(act.action_type, {}).get("addresses_causes", []))
        covered.update(addressed.intersection(input_cause_types))
    return sorted(list(covered))


def generate_scenarios(
    causes: list[Cause],
    current_state_df: pd.DataFrame | None = None,
    master_dir: Path | str = "data/master",
    config_path: Path | str = "config/actions.yaml",
    max_scenarios: int = 8,
) -> list[Scenario]:
    """
    Tự động sinh các kịch bản can thiệp (Scenario) dựa trên nguyên nhân nghẽn (Causes):
    - S0 = No Action (luôn luôn có mặt).
    - Tạo các kịch bản hành động đơn lẻ (single-action).
    - Tạo các kịch bản kết hợp 2 hành động hợp lý (2-action combination).
    - Lọc tĩnh (static feasibility) để loại kịch bản không khả thi.
    - Pre-rank theo độ phủ nguyên nhân (coverage) cao và độ xáo trộn (disruption) thấp.
    - Giới hạn tối đa `max_scenarios` (mặc định 8).
    """
    actions_cfg = load_action_config(config_path)

    # 1. Luôn tạo S0 (Baseline)
    s0 = Scenario(
        scenario_id="S0",
        actions=[],
        cause_coverage=[],
        estimated_disruption=0.0,
    )

    if not causes:
        return [s0]

    # 2. Lấy candidate actions
    candidates = get_candidate_actions(causes, config_path=config_path)
    if not candidates:
        return [s0]

    potential_scenarios: list[Scenario] = []

    # 3. Tạo single-action scenarios
    for act in candidates:
        coverage = calculate_cause_coverage([act], causes, actions_cfg)
        disruption = get_action_disruption(act.action_type, config_path=config_path)
        potential_scenarios.append(
            Scenario(
                scenario_id="TMP",
                actions=[act],
                cause_coverage=coverage,
                estimated_disruption=disruption,
            )
        )

    # 4. Tạo 2-action combinations
    if len(candidates) >= 2:
        for act_a, act_b in combinations(candidates, 2):
            combined_actions = [act_a, act_b]
            coverage = calculate_cause_coverage(combined_actions, causes, actions_cfg)
            disruption = (
                get_action_disruption(act_a.action_type, config_path=config_path)
                + get_action_disruption(act_b.action_type, config_path=config_path)
            )
            potential_scenarios.append(
                Scenario(
                    scenario_id="TMP",
                    actions=combined_actions,
                    cause_coverage=coverage,
                    estimated_disruption=disruption,
                )
            )

    # 5. Lọc qua static feasibility
    feasible_scenarios: list[Scenario] = []
    for sc in potential_scenarios:
        feas_res = check_static_feasibility(
            sc,
            current_state_df=current_state_df,
            master_dir=master_dir,
            config_path=config_path,
        )
        if feas_res.is_feasible:
            feasible_scenarios.append(sc)

    # 6. Pre-rank: Ưu tiên cause coverage cao -> disruption thấp
    feasible_scenarios.sort(
        key=lambda s: (-len(s.cause_coverage), s.estimated_disruption)
    )

    # 7. Cắt bớt theo max_scenarios - 1 (vì dành 1 chỗ cho S0)
    top_feasible = feasible_scenarios[: max_scenarios - 1]

    # 8. Đánh số lại ID: S0, S1, S2, ...
    result: list[Scenario] = [s0]
    for idx, sc in enumerate(top_feasible, start=1):
        sc.scenario_id = f"S{idx}"
        result.append(sc)

    return result
