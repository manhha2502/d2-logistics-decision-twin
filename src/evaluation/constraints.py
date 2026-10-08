from pathlib import Path
from typing import Any
import yaml

from src.common.schemas import Scenario, SimulationResult

DEFAULT_DECISION_CONFIG = Path("config/decision_modes.yaml")


def load_dynamic_constraints_config(config_path: Path | str = DEFAULT_DECISION_CONFIG) -> dict[str, Any]:
    """Tải cấu hình dynamic constraints từ YAML."""
    path = Path(config_path)
    if not path.is_file():
        return {
            "max_buffer_overflow": 0.0,
            "max_starvation_minutes": 0.0,
            "max_unmet_consumption": 0.0,
            "reject_secondary_bottleneck": True,
            "secondary_bottleneck_penalty": 0.50,
        }
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("dynamic_constraints", {})


def check_dynamic_constraints(
    sim_result: SimulationResult,
    config: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """
    Kiểm tra một kết quả mô phỏng SimPy có vi phạm các ràng buộc động nghiêm trọng không:
    - Tràn buffer (buffer overflow)
    - Đói chuyền (starvation / unmet consumption)
    - Gây nghẽn phụ (secondary bottleneck trên R2)
    """
    if config is None:
        config = load_dynamic_constraints_config()

    reasons: list[str] = []
    max_overflow = float(config.get("max_buffer_overflow", 0.0))
    max_starv = float(config.get("max_starvation_minutes", 0.0))
    max_unmet = float(config.get("max_unmet_consumption", 0.0))
    reject_sec = bool(config.get("reject_secondary_bottleneck", True))
    max_late = float(config.get("max_late_delivery_count", 5))
    max_util = float(config.get("max_amr_utilization", 0.95))

    if sim_result.buffer_overflow > max_overflow:
        reasons.append(f"BUFFER_OVERFLOW: {sim_result.buffer_overflow:.2f} > {max_overflow}")

    if sim_result.starvation_minutes > max_starv:
        reasons.append(f"STARVATION_DETECTED: {sim_result.starvation_minutes:.2f} min > {max_starv}")

    if sim_result.unmet_consumption > max_unmet:
        reasons.append(f"UNMET_CONSUMPTION: {sim_result.unmet_consumption:.2f} > {max_unmet}")

    if reject_sec and sim_result.secondary_bottleneck:
        reasons.append("CRITICAL_SECONDARY_BOTTLENECK")

    if sim_result.late_delivery_count > max_late:
        reasons.append(f"SEVERE_LATE_DELIVERY: {sim_result.late_delivery_count} > {max_late}")

    if hasattr(sim_result, "amr_utilization") and isinstance(sim_result.amr_utilization, dict):
        for amr_id, util in sim_result.amr_utilization.items():
            if util > max_util:
                reasons.append(f"UNACCEPTABLE_RESOURCE_OVERLOAD: {amr_id} utilization {util:.2f} > {max_util}")

    return len(reasons) == 0, reasons


def apply_dynamic_constraints(
    scenarios: list[Scenario],
    sim_results: dict[str, SimulationResult],
    config_path: Path | str = DEFAULT_DECISION_CONFIG,
) -> tuple[list[Scenario], dict[str, list[str]]]:
    """
    Lọc danh sách Scenario sau khi chạy SimPy:
    - Loại bỏ các kịch bản vi phạm dynamic constraints.
    - S0 (baseline) luôn được giữ lại để làm đối chứng.
    Trả về (valid_scenarios, rejected_reasons_by_scenario_id).
    """
    cfg = load_dynamic_constraints_config(config_path)
    valid_scenarios: list[Scenario] = []
    rejected: dict[str, list[str]] = {}

    for sc in scenarios:
        # S0 luôn được giữ lại
        if sc.scenario_id == "S0":
            valid_scenarios.append(sc)
            continue

        res = sim_results.get(sc.scenario_id)
        if not res:
            rejected[sc.scenario_id] = ["MISSING_SIMULATION_RESULT"]
            continue

        is_passed, reasons = check_dynamic_constraints(res, cfg)
        if is_passed:
            valid_scenarios.append(sc)
        else:
            rejected[sc.scenario_id] = reasons

    return valid_scenarios, rejected
