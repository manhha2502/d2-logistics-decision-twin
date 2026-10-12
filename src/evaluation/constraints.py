from pathlib import Path
from typing import Any
import yaml

from src.common.schemas import Scenario, SimulationResult

DEFAULT_DECISION_CONFIG = Path("config/decision_modes.yaml")


def load_dynamic_constraints_config(config_path: Path | str = DEFAULT_DECISION_CONFIG) -> dict[str, Any]:
    """Tải cấu hình dynamic constraints từ YAML."""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Decision configuration not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("dynamic_constraints", {})


def check_dynamic_constraints(
    sim_result: SimulationResult,
    config: dict[str, Any] | None = None,
    baseline_result: SimulationResult | None = None,
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
    max_overflow = float(config["max_buffer_overflow"])
    max_starv = float(config["max_starvation_minutes"])
    max_unmet = float(config["max_unmet_consumption"])
    reject_sec = bool(config["reject_secondary_bottleneck"])
    max_late = float(config["max_late_delivery_count"])
    max_util = float(config["max_amr_utilization"])

    if sim_result.buffer_overflow > max_overflow:
        reasons.append(f"BUFFER_OVERFLOW: {sim_result.buffer_overflow:.2f} > {max_overflow}")

    if sim_result.starvation_minutes > max_starv:
        reasons.append(f"STARVATION_DETECTED: {sim_result.starvation_minutes:.2f} min > {max_starv}")

    if sim_result.unmet_consumption > max_unmet:
        reasons.append(f"UNMET_CONSUMPTION: {sim_result.unmet_consumption:.2f} > {max_unmet}")

    if reject_sec and sim_result.secondary_bottleneck:
        reasons.append("CRITICAL_SECONDARY_BOTTLENECK")

    # Existing congestion in S0 is not caused by an intervention. Reject an
    # intervention when it makes an already severe late count worse.
    if sim_result.late_delivery_count > max_late and (
        baseline_result is None or sim_result.late_delivery_count > baseline_result.late_delivery_count
    ):
        reasons.append(f"SEVERE_LATE_DELIVERY: {sim_result.late_delivery_count} > {max_late}")

    if hasattr(sim_result, "amr_utilization") and isinstance(sim_result.amr_utilization, dict):
        for amr_id, util in sim_result.amr_utilization.items():
            baseline_util = baseline_result.amr_utilization.get(amr_id, 0.0) if baseline_result else 0.0
            if util > max_util and (baseline_result is None or util > baseline_util + 1e-9):
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

        is_passed, reasons = check_dynamic_constraints(res, cfg, sim_results.get("S0"))
        if is_passed:
            valid_scenarios.append(sc)
        else:
            rejected[sc.scenario_id] = reasons

    return valid_scenarios, rejected
