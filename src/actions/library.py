from pathlib import Path
from typing import Any
import yaml

from src.common.schemas import Action, Cause

DEFAULT_CONFIG_PATH = Path("config/actions.yaml")


def load_action_config(config_path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Tải cấu hình action library từ file YAML."""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file cấu hình actions: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("actions", {})


def get_candidate_actions(
    causes: list[Cause],
    config_path: Path | str = DEFAULT_CONFIG_PATH
) -> list[Action]:
    """
    Từ danh sách các Cause đã được chẩn đoán, tra cứu các Action phù hợp.
    Trả về danh sách các Action cụ thể với default parameters.
    """
    actions_cfg = load_action_config(config_path)
    cause_types = {c.cause_type for c in causes}

    candidate_types: set[str] = set()
    for act_type, act_data in actions_cfg.items():
        addressed = set(act_data.get("addresses_causes", []))
        if addressed.intersection(cause_types):
            candidate_types.add(act_type)

    actions: list[Action] = []
    idx = 1
    # Sắp xếp để đảm bảo thứ tự deterministic
    for act_type in sorted(candidate_types):
        act_info = actions_cfg.get(act_type, {})
        params = dict(act_info.get("default_params", {}))
        
        # Đảm bảo mọi action đều có start_time và duration_min theo convention
        if "start_time" not in params:
            params["start_time"] = "NOW"
        if "duration_min" not in params:
            params["duration_min"] = 45

        actions.append(
            Action(
                action_id=f"ACT_{idx:02d}",
                action_type=act_type,
                parameters=params,
            )
        )
        idx += 1

    return actions


def get_action_conflicts(
    action_type: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH
) -> list[str]:
    """Lấy danh sách các action types xung đột với action_type cho trước."""
    actions_cfg = load_action_config(config_path)
    return actions_cfg.get(action_type, {}).get("conflicts_with", [])


def get_action_disruption(
    action_type: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH
) -> float:
    """Lấy mức độ xáo trộn (disruption level) của action."""
    actions_cfg = load_action_config(config_path)
    return float(actions_cfg.get(action_type, {}).get("disruption_level", 1.0))
