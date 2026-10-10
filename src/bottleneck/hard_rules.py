"""Config-driven hard bottleneck rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.common.schemas import FutureState

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config/thresholds.yaml"


def load_thresholds(source: Any = None) -> dict[str, Any]:
    if isinstance(source, dict):
        source = source.get("thresholds", source)
        if isinstance(source, dict):
            return source
    path = Path(source) if source else DEFAULT_CONFIG
    with path.open(encoding="utf-8") as stream:
        data = yaml.safe_load(stream) or {}
    if not data:
        raise ValueError(f"threshold configuration is empty: {path}")
    return data


def _overflow_parts(state: FutureState) -> tuple[float, float]:
    """Recover staging and line-buffer overflow from the shared state fields."""
    queue_overflow = max(0.0, state.queue_start + state.demand - state.throughput - state.queue_end)
    buffer_overflow = max(0.0, state.overflow - queue_overflow) if state.location == "R1" else 0.0
    return queue_overflow, buffer_overflow


def evaluate_hard_rules(state: FutureState, thresholds: Any = None) -> dict[str, str]:
    """Return triggered rule names mapped to their minimum severity."""
    cfg = load_thresholds(thresholds)
    dcr, queue, utilization, buffer = cfg["dcr"], cfg["queue"], cfg["utilization"], cfg["buffer"]
    triggered: dict[str, str] = {}
    if state.dcr >= float(dcr["critical"]):
        triggered["DCR_CRITICAL"] = "Critical"
    elif state.dcr >= float(dcr["high"]):
        triggered["DCR_HIGH"] = "High"
    if state.queue_end - state.queue_start >= float(queue["growth"]):
        triggered["QUEUE_GROWTH"] = "High"
    if state.utilization >= float(utilization["high"]):
        triggered["HIGH_UTILIZATION"] = "High"

    if state.location == "R1":
        ratios = (
            state.buffer_mat_a / float(buffer["capacity_mat_a"]),
            state.buffer_mat_b / float(buffer["capacity_mat_b"]),
        )
        if min(ratios) <= float(buffer["critical_ratio"]):
            triggered["CRITICAL_LOW_BUFFER"] = "Critical"
        elif min(ratios) <= float(buffer["low_ratio"]):
            triggered["LOW_BUFFER"] = "High"
        if _overflow_parts(state)[1] > 0:
            triggered["BUFFER_OVERFLOW"] = "High"
        if state.unmet_consumption > 0:
            triggered["UNMET_CONSUMPTION"] = "Critical"
    return triggered


def trigger_hard_rules(state: FutureState, thresholds: Any = None) -> list[str]:
    """Compatibility helper returning only rule names."""
    return list(evaluate_hard_rules(state, thresholds))
