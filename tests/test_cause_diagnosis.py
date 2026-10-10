from datetime import datetime

import pandas as pd

from src.bottleneck.cause_diagnosis import diagnose_bottleneck_causes, diagnose_causes
from src.common.schemas import FutureState


def state(**changes):
    values = dict(
        timestamp=datetime(2026, 10, 8, 14, 15), location="R1", demand=15, capacity=10,
        dcr=1.5, throughput=10, queue_start=0, queue_end=5, waiting_time=7.5,
        utilization=1, buffer_mat_a=2, buffer_mat_b=18, unmet_consumption=1,
        overflow=0, amr_available=2,
    )
    values.update(changes)
    return FutureState(**values)


def test_multi_cause_diagnosis_has_specific_evidence():
    baseline = state(demand=8, amr_available=3, buffer_mat_a=15, unmet_consumption=0)
    forecast = {
        "travel_loaded": {"p50": 7}, "picking_time": {"p50": 3},
        "loading_time": {"p50": 2}, "unloading_time": {"p50": 2},
    }
    baseline_forecast = {
        "demand": baseline.demand, "amr_available": baseline.amr_available,
        "travel_loaded": {"p50": 5}, "picking_time": {"p50": 2},
        "loading_time": {"p50": 1}, "unloading_time": {"p50": 1},
    }
    # State baseline and driver baseline can coexist in a single mapping.
    baseline_forecast.update(vars(baseline))
    causes = diagnose_causes(state(), baseline_forecast, forecast)
    names = {cause.cause_type for cause in causes}
    assert {"DEMAND_SPIKE", "AMR_AVAILABILITY_DROP", "TRAVEL_TIME_INCREASE",
            "PICKING_SLOWDOWN", "HANDLING_TIME_INCREASE", "BUFFER_LOW"} <= names
    assert all(cause.evidence for cause in causes)


def test_full_buffer_is_reported():
    causes = diagnose_causes(state(buffer_mat_a=28, buffer_mat_b=24, unmet_consumption=0, overflow=2))
    assert "BUFFER_FULL" in {cause.cause_type for cause in causes}


def test_public_diagnosis_alias_uses_shared_cause_schema():
    causes = diagnose_bottleneck_causes(state())
    assert causes
    assert all(hasattr(cause, "cause_type") and hasattr(cause, "evidence") for cause in causes)


def test_maintenance_cause_is_confined_to_resource_route():
    event = pd.DataFrame([{
        "start_time": datetime(2026, 10, 8, 14, 0), "end_time": datetime(2026, 10, 8, 15, 0),
        "event_type": "AMR_MAINTENANCE", "target_id": "AMR03", "magnitude": 1,
    }])
    r2 = state(location="R2", timestamp=datetime(2026, 10, 8, 14, 30), demand=2,
               capacity=8, dcr=.25, amr_available=2, buffer_mat_a=16, unmet_consumption=0)
    r1 = state(timestamp=datetime(2026, 10, 8, 14, 30))
    assert "AMR_AVAILABILITY_DROP" not in {c.cause_type for c in diagnose_causes(r2, known_events=event)}
    assert "AMR_AVAILABILITY_DROP" in {c.cause_type for c in diagnose_causes(r1, known_events=event)}


def test_demand_spike_requires_real_baseline():
    causes = diagnose_causes(state(demand=100, capacity=10, buffer_mat_a=16, unmet_consumption=0))
    assert "DEMAND_SPIKE" not in {cause.cause_type for cause in causes}


def test_queue_overflow_does_not_fabricate_full_line_buffer():
    causes = diagnose_causes(state(
        demand=20, throughput=10, queue_end=2, buffer_mat_a=16, buffer_mat_b=14,
        unmet_consumption=0, overflow=8,
    ))
    assert "BUFFER_FULL" not in {cause.cause_type for cause in causes}
