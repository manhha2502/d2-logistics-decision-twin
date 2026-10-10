"""Continuous, explainable bottleneck risk score."""

from __future__ import annotations

from typing import Any

from src.bottleneck.hard_rules import load_thresholds
from src.common.schemas import FutureState


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def calculate_risk_components(state: FutureState, thresholds: Any = None) -> dict[str, float]:
    cfg = load_thresholds(thresholds)
    buffer = cfg["buffer"]
    minimum_buffer_ratio = min(
        state.buffer_mat_a / float(buffer["capacity_mat_a"]),
        state.buffer_mat_b / float(buffer["capacity_mat_b"]),
    ) if state.location == "R1" else 1.0
    return {
        "dcr": _clip(state.dcr / float(cfg["dcr"]["critical"])),
        "queue_growth": _clip((state.queue_end - state.queue_start) / float(cfg["queue"]["max_for_risk"])),
        "waiting": _clip(state.waiting_time / float(cfg["waiting_time"]["max_for_risk"])),
        "utilization": _clip(state.utilization),
        "buffer": _clip(1.0 - minimum_buffer_ratio / float(buffer["low_ratio"])),
    }


def calculate_risk_score(state: FutureState, thresholds: Any = None) -> float:
    cfg = load_thresholds(thresholds)
    components = calculate_risk_components(state, cfg)
    weights = cfg["risk"]["weights"]
    total_weight = sum(float(weights[name]) for name in components)
    if total_weight <= 0:
        raise ValueError("risk weights must sum to a positive value")
    return round(100.0 * sum(components[name] * float(weights[name]) for name in components) / total_weight, 2)
