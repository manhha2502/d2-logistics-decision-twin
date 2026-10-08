from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class QuantileValue:
    p10: float
    p50: float
    p90: float


@dataclass
class ForecastPoint:
    timestamp: datetime
    demand: QuantileValue
    travel_loaded: QuantileValue
    travel_empty: QuantileValue
    picking_time: QuantileValue
    loading_time: QuantileValue
    unloading_time: QuantileValue


@dataclass
class FutureState:
    timestamp: datetime
    location: str

    demand: float
    capacity: float
    dcr: float

    throughput: float

    queue_start: float
    queue_end: float
    waiting_time: float

    utilization: float

    buffer_mat_a: float
    buffer_mat_b: float

    unmet_consumption: float
    overflow: float

    amr_available: int


@dataclass
class BottleneckEvent:
    location: str
    predicted_time: datetime
    lead_time_min: int

    severity: str
    risk_score: float

    triggered_rules: list[str]
    evidence: dict[str, Any]


@dataclass
class Cause:
    cause_type: str
    contribution: str
    evidence: dict[str, Any]


@dataclass
class Action:
    action_id: str
    action_type: str
    parameters: dict[str, Any]


@dataclass
class Scenario:
    scenario_id: str
    actions: list[Action]
    cause_coverage: list[str]
    estimated_disruption: float = 0.0


@dataclass
class SimulationResult:
    scenario_id: str

    avg_waiting_time: float
    max_waiting_time: float

    avg_queue: float
    max_queue: float

    late_delivery_count: int

    throughput: float
    service_level: float

    starvation_minutes: float
    unmet_consumption: float

    buffer_overflow: float

    amr_utilization: dict[str, float]

    secondary_bottleneck: bool

    extra_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionPackage:
    bottleneck: BottleneckEvent

    causes: list[Cause]

    recommended_scenario: Scenario

    baseline_result: SimulationResult
    recommended_result: SimulationResult

    kpi_improvement: dict[str, Any]

    robustness: dict[str, Any]

    side_effects: dict[str, Any]