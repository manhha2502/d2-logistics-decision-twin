from dataclasses import dataclass
from pathlib import Path
from typing import Any
import pandas as pd

from src.actions.library import get_action_conflicts
from src.common.schemas import Scenario, Action


@dataclass
class FeasibilityResult:
    is_feasible: bool
    rejection_reasons: list[str]


def load_master_and_state(
    current_state_path: Path | str = "data/current/current_state.csv",
    master_dir: Path | str = "data/master",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Tải dữ liệu current_state, resource_master, route_master, material_master."""
    curr_df = pd.read_csv(current_state_path)
    res_df = pd.read_csv(Path(master_dir) / "resource_master.csv")
    route_df = pd.read_csv(Path(master_dir) / "route_master.csv")
    mat_path = Path(master_dir) / "material_master.csv"
    mat_df = pd.read_csv(mat_path) if mat_path.is_file() else pd.DataFrame()
    return curr_df, res_df, route_df, mat_df


def check_action_feasibility(
    action: Action,
    curr_state_df: pd.DataFrame,
    res_master_df: pd.DataFrame,
    route_master_df: pd.DataFrame,
    mat_master_df: pd.DataFrame | None = None,
) -> tuple[bool, list[str]]:
    """Kiểm tra tính khả thi tĩnh của từng Action đơn lẻ."""
    reasons: list[str] = []
    act_type = action.action_type
    params = action.parameters

    # Kiểm tra route compatibility
    known_routes = set(route_master_df["route_id"]) if not route_master_df.empty else set()
    for route_param in ["target_route", "from_route", "to_route"]:
        if route_param in params and params[route_param] not in known_routes:
            reasons.append(f"UNKNOWN_ROUTE: {params[route_param]} not in route_master")

    if act_type == "ALTERNATE_ROUTE":
        target_route = params.get("target_route", "R1")
        # Tìm đích đến của target_route
        match_route = route_master_df[route_master_df["route_id"] == target_route]
        if match_route.empty:
            reasons.append(f"TARGET_ROUTE_NOT_FOUND: {target_route}")
        else:
            dest = match_route.iloc[0]["destination"]
            # Kiểm tra xem có tuyến nào khác có cùng điểm đích không
            other_routes = route_master_df[
                (route_master_df["destination"] == dest) & (route_master_df["route_id"] != target_route)
            ]
            if other_routes.empty:
                reasons.append("NO_ALTERNATIVE_ROUTE_CONFIGURED")

    elif act_type == "REASSIGN_AMR":
        from_route = params.get("from_route", "R2")
        count_needed = int(params.get("count", 1))

        # Lấy danh sách AMR thuộc from_route trong master
        from_amrs = set(res_master_df[res_master_df["home_route"] == from_route]["resource_id"])

        # Kiểm tra trạng thái hiện tại trong current_state.csv
        # current_state có format: entity_type, entity_id, metric, value
        amr_status: dict[str, dict[str, Any]] = {}
        for _, row in curr_state_df[curr_state_df["entity_type"] == "RESOURCE"].iterrows():
            eid = row["entity_id"]
            if eid in from_amrs:
                if eid not in amr_status:
                    amr_status[eid] = {}
                amr_status[eid][row["metric"]] = row["value"]

        # Đếm số AMR thực sự khả dụng (available == 1, battery >= 20%)
        available_count = 0
        for eid, metrics in amr_status.items():
            avail = str(metrics.get("available", "0")) in ["1", "1.0", "True", "true"]
            try:
                battery = float(metrics.get("battery_pct", 0.0))
            except (ValueError, TypeError):
                battery = 0.0

            # Ngưỡng pin tối thiểu từ master hoặc mặc định 20%
            min_battery = 20.0
            res_row = res_master_df[res_master_df["resource_id"] == eid]
            if not res_row.empty:
                min_battery = float(res_row.iloc[0].get("min_dispatch_battery_pct", 20.0))

            if avail and battery >= min_battery:
                available_count += 1

        if available_count < count_needed:
            reasons.append(
                f"INSUFFICIENT_AVAILABLE_AMR: needed {count_needed}, available {available_count} on route {from_route}"
            )

    elif act_type == "CONSOLIDATE_DELIVERY":
        batch_size = int(params.get("batch_size_totes", 3))
        # AMR payload tối đa trong master là 3 totes
        max_payload = 3
        if not res_master_df.empty:
            max_payload = int(res_master_df["payload_totes"].max())
        if batch_size > max_payload:
            reasons.append(f"BATCH_SIZE_EXCEEDS_PAYLOAD: {batch_size} > {max_payload}")

    elif act_type == "ADJUST_REPLENISHMENT_TIME":
        # Buffer limits check: nếu buffer đang đầy (fill_ratio >= 1.0) mà yêu cầu cấp sớm (shift < 0) -> nguy cơ tràn
        shift_min = int(params.get("shift_minutes", -15))
        if shift_min < 0 and not curr_state_df.empty:
            # Kiểm tra fill_ratio của buffer trong current_state
            buffer_rows = curr_state_df[
                (curr_state_df["entity_type"] == "BUFFER") & (curr_state_df["metric"] == "fill_ratio")
            ]
            for _, r in buffer_rows.iterrows():
                try:
                    fill = float(r["value"])
                    if fill >= 0.98:
                        reasons.append(f"BUFFER_NEAR_FULL: {r['entity_id']} fill ratio {fill:.2f} >= 0.98")
                except (ValueError, TypeError):
                    pass

    return len(reasons) == 0, reasons


def check_static_feasibility(
    scenario: Scenario,
    current_state_df: pd.DataFrame | None = None,
    master_dir: Path | str = "data/master",
    config_path: Path | str = "config/actions.yaml",
) -> FeasibilityResult:
    """
    Kiểm tra tính khả thi tĩnh của kịch bản (Scenario) TRƯỚC KHI chạy SimPy:
    1. Kiểm tra xung đột giữa các actions trong cùng scenario.
    2. Kiểm tra tính hợp lệ về tài nguyên (AMR, route, alternate route).
    """
    reasons: list[str] = []

    # S0 luôn khả thi
    if scenario.scenario_id == "S0" or len(scenario.actions) == 0:
        return FeasibilityResult(is_feasible=True, rejection_reasons=[])

    # 1. Kiểm tra xung đột hành động
    actions = scenario.actions
    for i in range(len(actions)):
        for j in range(i + 1, len(actions)):
            act_i = actions[i].action_type
            act_j = actions[j].action_type
            conflicts_i = get_action_conflicts(act_i, config_path)
            conflicts_j = get_action_conflicts(act_j, config_path)
            if act_j in conflicts_i or act_i in conflicts_j:
                reasons.append(f"ACTION_CONFLICT: {act_i} conflicts with {act_j}")

    # 2. Tải dữ liệu master nếu chưa có
    try:
        if current_state_df is None:
            curr_df, res_df, route_df, mat_df = load_master_and_state(master_dir=master_dir)
        else:
            curr_df = current_state_df
            res_df = pd.read_csv(Path(master_dir) / "resource_master.csv")
            route_df = pd.read_csv(Path(master_dir) / "route_master.csv")
            mat_path = Path(master_dir) / "material_master.csv"
            mat_df = pd.read_csv(mat_path) if mat_path.is_file() else pd.DataFrame()
    except Exception as e:
        reasons.append(f"DATA_LOAD_ERROR: {str(e)}")
        return FeasibilityResult(is_feasible=False, rejection_reasons=reasons)

    # 3. Kiểm tra từng action
    for act in actions:
        is_ok, act_reasons = check_action_feasibility(act, curr_df, res_df, route_df, mat_df)
        if not is_ok:
            reasons.extend(act_reasons)

    return FeasibilityResult(
        is_feasible=len(reasons) == 0,
        rejection_reasons=reasons,
    )
