"""
metrics.py — KPI collector (Task 7).

KPIs are computed on the target route (R1); R2 is tracked separately for the
secondary-bottleneck check.  Requests still unserved at the horizon are
*censored*: their wait so far is counted, so a stuck queue can never look good.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .entities import MaterialRequest


@dataclass
class SimulationMetrics:
    late_threshold_min: float
    requests: List[MaterialRequest] = field(default_factory=list)
    queue_samples: Dict[str, List[float]] = field(default_factory=dict)
    queue_at_interval: Dict[str, List[float]] = field(default_factory=dict)

    throughput_totes: Dict[str, float] = field(default_factory=dict)
    buffer_overflow: float = 0.0
    unmet_consumption: float = 0.0
    unmet_by_material: Dict[str, float] = field(default_factory=dict)
    starvation_minutes: float = 0.0
    starvation_events: List[Tuple[str, float, float]] = field(default_factory=list)
    trips_completed: Dict[str, int] = field(default_factory=dict)
    buffer_min_level: Dict[str, float] = field(default_factory=dict)
    picker_busy_time: float = 0.0
    trip_log: List[tuple] = field(default_factory=list)   # (amr_id, route, start, end, totes)
    busy_by_route: Dict[str, float] = field(default_factory=dict)
    pool_minutes: Dict[str, float] = field(default_factory=dict)   # sum of (AMRs serving route) x time
    secondary_bottleneck: bool = False

    # ---- recording -----------------------------------------------------
    def register_request(self, req: MaterialRequest) -> None:
        self.requests.append(req)

    def record_queue(self, route: str, totes: float) -> None:
        self.queue_samples.setdefault(route, []).append(totes)

    def record_interval_queue(self, route: str, totes: float) -> None:
        self.queue_at_interval.setdefault(route, []).append(round(totes, 4))

    def record_delivery(self, route: str, totes: float) -> None:
        self.throughput_totes[route] = self.throughput_totes.get(route, 0.0) + totes

    # ---- KPIs ------------------------------------------------------------
    def waits(self, route: str, horizon: float) -> List[float]:
        """Wait from need time to AMR pickup; unserved requests are censored at horizon."""
        out = []
        for r in self.requests:
            if r.route != route or r.created_at > horizon:
                continue
            end = r.served_at if r.served_at is not None else horizon
            out.append(max(0.0, end - r.created_at))
        return out

    def avg_wait(self, route: str, horizon: float) -> float:
        w = self.waits(route, horizon)
        return sum(w) / len(w) if w else 0.0

    def max_wait(self, route: str, horizon: float) -> float:
        w = self.waits(route, horizon)
        return max(w) if w else 0.0

    def late_count(self, route: str, horizon: float) -> int:
        return sum(1 for x in self.waits(route, horizon) if x > self.late_threshold_min)

    def service_level(self, route: str, horizon: float) -> float:
        w = self.waits(route, horizon)
        if not w:
            return 1.0
        return max(0.0, 1.0 - self.late_count(route, horizon) / len(w))

    def avg_queue(self, route: str) -> float:
        s = self.queue_samples.get(route, [])
        return sum(s) / len(s) if s else 0.0

    def max_queue(self, route: str) -> float:
        s = self.queue_samples.get(route, [])
        return max(s) if s else 0.0
