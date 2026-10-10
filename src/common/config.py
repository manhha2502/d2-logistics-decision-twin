"""Project-root configuration loading without reading validation labels."""
from pathlib import Path
import math
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    pass


def load_config(root=None):
    """Load all four YAML files; reject invalid settings and runtime paths.

    Empty thresholds are reported as an unfinished upstream module. They are
    never replaced by invented thresholds. This permits dashboard startup.
    """
    root = Path(root or PROJECT_ROOT).resolve()
    result = {"root": root, "config_paths": {}, "readiness_warnings": []}
    for name, filename in (("system", "system.yaml"), ("thresholds", "thresholds.yaml"),
                           ("actions", "actions.yaml"), ("decision", "decision_modes.yaml")):
        path = root / "config" / filename
        if not path.is_file():
            raise ConfigError(f"Missing configuration: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
        if data is None and name == "thresholds":
            data = {}
            result["readiness_warnings"].append("config/thresholds.yaml is empty (module Hà).")
        if not isinstance(data, dict) or (not data and name != "thresholds"):
            raise ConfigError(f"Expected non-empty mapping: {path}")
        result[name] = data
        result["config_paths"][name] = path
    system = result["system"]
    for key in ("timezone", "target_line", "target_route", "horizon_min", "interval_min",
                "max_scenarios", "default_decision_mode", "seed", "snapshot_time", "paths"):
        if key not in system:
            raise ConfigError(f"system.yaml missing field: {key}")
    for key in ("horizon_min", "interval_min", "max_scenarios", "seed"):
        if type(system[key]) is not int:
            raise ConfigError(f"{key} must be an integer")
    if system["horizon_min"] != 60 or system["interval_min"] != 15:
        raise ConfigError("MVP requires horizon_min=60 and interval_min=15")
    if not 1 <= system["max_scenarios"] <= 8:
        raise ConfigError("max_scenarios must be between 1 and 8")
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        datetime.fromisoformat(str(system["snapshot_time"]))
        ZoneInfo(system["timezone"])
    except (ValueError, KeyError) as exc:
        raise ConfigError(f"Invalid snapshot_time/timezone: {exc}") from exc
    if not isinstance(system["paths"], dict):
        raise ConfigError("paths must be a mapping")
    result["paths"] = {}
    for key in ("current_state", "known_events", "production_plan", "master_dir", "artifacts_dir"):
        value = system["paths"].get(key)
        if not isinstance(value, str) or not value:
            raise ConfigError(f"Missing/invalid path: {key}")
        path = (root / value).resolve()
        if not path.is_relative_to(root) or "validation_only" in [p.lower() for p in path.parts]:
            raise ConfigError(f"Forbidden runtime path: {value}")
        if key != "artifacts_dir" and not path.exists():
            raise ConfigError(f"Path does not exist: {path}")
        result["paths"][key] = path
    for key in ("actions",):
        if not isinstance(result[key].get(key), dict) or not result[key][key]:
            raise ConfigError("actions.yaml requires actions mapping")
    for key in ("decision_modes", "dynamic_constraints", "robustness"):
        if not isinstance(result["decision"].get(key), dict):
            raise ConfigError(f"decision_modes.yaml missing mapping: {key}")
    if system["default_decision_mode"] not in result["decision"]["decision_modes"]:
        raise ConfigError("Unknown default_decision_mode")
    for mode, info in result["decision"]["decision_modes"].items():
        weights = info.get("weights") if isinstance(info, dict) else None
        if not isinstance(weights, dict) or not weights or any(
            not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in weights.values()
        ) or abs(sum(weights.values()) - 1) > 1e-6:
            raise ConfigError(f"Invalid weights for decision mode: {mode}")
    robust = result["decision"]["robustness"]
    if type(robust.get("top_k_scenarios")) is not int or robust["top_k_scenarios"] < 1:
        raise ConfigError("robustness.top_k_scenarios must be positive integer")
    reduction = robust.get("adverse_reduce_amr_count", 0)
    if type(reduction) is not int or reduction < 0:
        raise ConfigError("robustness.adverse_reduce_amr_count must be a nonnegative integer")
    if type(robust.get("enable_adverse_amr_reduction", False)) is not bool:
        raise ConfigError("robustness.enable_adverse_amr_reduction must be boolean")
    return result
