"""Convert future states into explainable bottleneck events."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from src.bottleneck.hard_rules import _overflow_parts, evaluate_hard_rules, load_thresholds
from src.bottleneck.risk_score import calculate_risk_components, calculate_risk_score
from src.common.schemas import BottleneckEvent, FutureState

_RANK = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}


def _score_severity(score: float, cfg: dict[str, Any]) -> str:
    levels = cfg["risk"]["severity"]
    if score >= float(levels["critical"]):
        return "Critical"
    if score >= float(levels["high"]):
        return "High"
    if score >= float(levels["medium"]):
        return "Medium"
    return "Low"


def detect_bottlenecks(
    future_states: Iterable[FutureState],
    now: datetime | None = None,
    thresholds: Any = None,
) -> list[BottleneckEvent]:
    states = list(future_states)
    if not states:
        return []
    cfg = load_thresholds(thresholds)
    origin = now or min(state.timestamp for state in states) - timedelta(minutes=15)
    events = []
    for state in sorted(states, key=lambda item: (item.timestamp, item.location)):
        rules = evaluate_hard_rules(state, cfg)
        score = calculate_risk_score(state, cfg)
        score_severity = _score_severity(score, cfg)
        # A low score with no hard rule is a healthy future state, not an event.
        if not rules and score_severity == "Low":
            continue
        hard_severity = max(rules.values(), key=_RANK.get) if rules else "Low"
        severity = max((score_severity, hard_severity), key=_RANK.get)
        events.append(BottleneckEvent(
            location=state.location,
            predicted_time=state.timestamp,
            lead_time_min=max(0, int((state.timestamp - origin).total_seconds() // 60)),
            severity=severity,
            risk_score=score,
            triggered_rules=list(rules),
            evidence={
                "demand": state.demand, "capacity": state.capacity, "dcr": state.dcr,
                "queue_start": state.queue_start, "queue_end": state.queue_end,
                "waiting_time": state.waiting_time, "utilization": state.utilization,
                "buffer_mat_a": state.buffer_mat_a, "buffer_mat_b": state.buffer_mat_b,
                "unmet_consumption": state.unmet_consumption, "overflow": state.overflow,
                "queue_overflow": _overflow_parts(state)[0],
                "buffer_overflow": _overflow_parts(state)[1],
                "amr_available": state.amr_available,
                "risk_components": calculate_risk_components(state, cfg),
            },
        ))
    return events
