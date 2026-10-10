from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.common.schemas import ForecastPoint, QuantileValue
from src.bottleneck.cause_diagnosis import diagnose_causes
from src.bottleneck.detector import detect_bottlenecks
from src.logistics.buffer import update_buffer
from src.logistics.capacity import calculate_transport_capacity
from src.logistics.future_state import build_future_states
from src.logistics.queue import calculate_queue_state


def q(value):
    return QuantileValue(value, value, value)


def point(timestamp, demand=8, process=1):
    return ForecastPoint(timestamp, q(demand), q(5), q(4), q(process), q(process), q(process))


def mock_forecast_future_drivers(now, horizon_min=60, interval_min=15) -> list[ForecastPoint]:
    """Development mock matching Dương's agreed forecast-service interface."""
    return [point(now + timedelta(minutes=minute), demand=11) for minute in range(interval_min, horizon_min + 1, interval_min)]


def test_queue_grows_only_when_work_exceeds_capacity():
    assert calculate_queue_state(2, 3, 8, 20)["queue_end"] == 0
    assert calculate_queue_state(2, 10, 8, 20)["queue_end"] == 4


def test_queue_records_staging_overflow():
    result = calculate_queue_state(10, 20, 5, 12)
    assert result["queue_end"] == 12
    assert result["overflow"] == 13


def test_buffer_is_bounded_and_reports_unmet():
    result = update_buffer(1, 0, 4, 10)
    assert result["next_level"] == 0
    assert result["unmet_consumption"] == 3


def test_capacity_uses_complete_cycle():
    assert calculate_transport_capacity(2, 3, 1, 15, 1, 5, 1, 3) == pytest.approx(9)


def test_maintenance_reduces_future_capacity():
    start = datetime(2026, 10, 8, 14, 0)
    times = [start + timedelta(minutes=minutes) for minutes in (15, 30, 45, 60)]
    events = pd.DataFrame([{
        "start_time": times[0], "end_time": times[-1], "event_type": "AMR_MAINTENANCE",
        "target_id": "AMR03", "magnitude": 1,
    }])
    states = build_future_states(
        "data/current/current_state.csv", [point(t) for t in times], events, {"now": start}
    )
    r1 = [state for state in states if state.location == "R1"]
    assert len(states) == 8
    assert [item.timestamp for item in r1] == times
    assert r1[0].amr_available == 2
    assert r1[-1].amr_available == 3
    assert r1[0].capacity < r1[-1].capacity


def test_future_state_rejects_wrong_mvp_horizon():
    start = datetime(2026, 10, 8, 14, 0)
    with pytest.raises(ValueError, match="exactly"):
        build_future_states(
            "data/current/current_state.csv",
            [point(start + timedelta(minutes=15)), point(start + timedelta(minutes=30))],
            known_events=[],
        )


def test_future_state_rejects_non_15_minute_intervals():
    start = datetime(2026, 10, 8, 14, 0)
    times = [start + timedelta(minutes=minutes) for minutes in (15, 30, 50, 60)]
    with pytest.raises(ValueError, match="15-minute"):
        build_future_states("data/current/current_state.csv", [point(t) for t in times], known_events=[])


def test_r2_capacity_does_not_follow_r1_process_forecast():
    start = datetime(2026, 10, 8, 14, 0)
    times = [start + timedelta(minutes=minute) for minute in (15, 30, 45, 60)]
    fast = [point(time, process=1) for time in times]
    slow = [point(time, process=3) for time in times]
    fast_r2 = [s.capacity for s in build_future_states("data/current/current_state.csv", fast, [], {"now": start}) if s.location == "R2"]
    slow_r2 = [s.capacity for s in build_future_states("data/current/current_state.csv", slow, [], {"now": start}) if s.location == "R2"]
    assert fast_r2 == slow_r2


def test_r2_history_ignores_observations_after_forecast_origin():
    start = datetime(2026, 10, 8, 14, 0)
    history = [
        {"timestamp": start - timedelta(minutes=15), "route_id": "R2", "loading_min": 1,
         "travel_loaded_min": 4, "unloading_min": 1, "travel_empty_min": 4},
        {"timestamp": start + timedelta(minutes=30), "route_id": "R2", "loading_min": 10,
         "travel_loaded_min": 10, "unloading_min": 10, "travel_empty_min": 10},
    ]
    states = build_future_states(
        "data/current/current_state.csv", mock_forecast_future_drivers(start), [],
        {"now": start, "r2_process_history": history},
    )
    r2 = next(state for state in states if state.location == "R2")
    assert r2.capacity == pytest.approx(calculate_transport_capacity(2, 3, .85, 15, 1, 4, 1, 4))


def test_known_production_plan_controls_material_buffers_without_double_counting_ramp():
    start = datetime(2026, 10, 8, 14, 0)
    forecasts = mock_forecast_future_drivers(start)
    plan_a = [
        {"timestamp": forecast.timestamp, "line_id": "LINE_A", "planned_mat_a_totes": 12,
         "planned_mat_b_totes": 0} for forecast in forecasts
    ]
    plan_b = [
        {"timestamp": forecast.timestamp, "line_id": "LINE_A", "planned_mat_a_totes": 0,
         "planned_mat_b_totes": 12} for forecast in forecasts
    ]
    ramp = [{"start_time": forecasts[0].timestamp, "end_time": forecasts[-1].timestamp,
             "event_type": "PRODUCTION_RAMP", "target_id": "LINE_A", "magnitude": 1.35}]
    states_a = build_future_states("data/current/current_state.csv", forecasts, ramp, {"now": start, "production_plan": plan_a})
    states_b = build_future_states("data/current/current_state.csv", forecasts, ramp, {"now": start, "production_plan": plan_b})
    a, b = states_a[0], states_b[0]
    assert a.demand == b.demand == forecasts[0].demand.p50
    assert a.buffer_mat_a < b.buffer_mat_a
    assert a.buffer_mat_b > b.buffer_mat_b


def test_mock_forecast_to_state_event_and_causes_chain():
    start = datetime(2026, 10, 8, 14, 0)
    forecasts = mock_forecast_future_drivers(start)
    states = build_future_states(
        "data/current/current_state.csv", forecasts,
        "data/known_future/known_future_events.csv", {"now": start},
    )
    events = detect_bottlenecks(states, now=start)
    r1 = next(state for state in states if state.location == "R1")
    causes = diagnose_causes(
        r1, baseline={"demand": 8, "amr_available": 3}, forecast=forecasts[0],
        known_events="data/known_future/known_future_events.csv",
    )
    assert len(states) == 8 and events and causes
    assert any(event.location == "R1" for event in events)
    assert {cause.cause_type for cause in causes} >= {"DEMAND_SPIKE", "AMR_AVAILABILITY_DROP"}
