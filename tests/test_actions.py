import pytest
import pandas as pd
from pathlib import Path

from src.common.schemas import Action, Cause, Scenario
from src.actions.library import (
    load_action_config,
    get_candidate_actions,
    get_action_conflicts,
    get_action_disruption,
)
from src.actions.feasibility import (
    check_action_feasibility,
    check_static_feasibility,
)
from src.actions.scenario_generator import generate_scenarios


def test_action_library_loads():
    """Kiểm tra việc load file config actions.yaml."""
    cfg = load_action_config("config/actions.yaml")
    assert "PRIORITIZE_REQUEST" in cfg
    assert "REASSIGN_AMR" in cfg
    assert "ALTERNATE_ROUTE" in cfg
    assert "ADJUST_REPLENISHMENT_TIME" in cfg
    assert "CONSOLIDATE_DELIVERY" in cfg


def test_candidate_actions_retrieval():
    """Kiểm tra tìm candidate actions từ causes."""
    causes = [
        Cause(cause_type="DEMAND_SPIKE", contribution="high", evidence={}),
        Cause(cause_type="AMR_AVAILABILITY_DROP", contribution="high", evidence={}),
    ]
    actions = get_candidate_actions(causes)
    action_types = {a.action_type for a in actions}
    assert "PRIORITIZE_REQUEST" in action_types
    assert "REASSIGN_AMR" in action_types


def test_alternate_route_rejected_with_current_dataset():
    """Kiểm tra ALTERNATE_ROUTE bị reject vì không có tuyến phụ tới LINE_A."""
    action = Action(
        action_id="A_ALT",
        action_type="ALTERNATE_ROUTE",
        parameters={"target_route": "R1"},
    )
    scenario = Scenario(
        scenario_id="S_TEST",
        actions=[action],
        cause_coverage=["TRAVEL_TIME_INCREASE"],
    )
    res = check_static_feasibility(scenario)
    assert not res.is_feasible
    assert any("NO_ALTERNATIVE_ROUTE_CONFIGURED" in r for r in res.rejection_reasons)


def test_conflicting_actions_rejected():
    """Kiểm tra 2 action xung đột bị loại (PRIORITIZE_REQUEST và CONSOLIDATE_DELIVERY)."""
    act1 = Action(
        action_id="A1",
        action_type="PRIORITIZE_REQUEST",
        parameters={"target_line": "LINE_A"},
    )
    act2 = Action(
        action_id="A2",
        action_type="CONSOLIDATE_DELIVERY",
        parameters={"target_route": "R1"},
    )
    scenario = Scenario(
        scenario_id="S_CONFLICT",
        actions=[act1, act2],
        cause_coverage=[],
    )
    res = check_static_feasibility(scenario)
    assert not res.is_feasible
    assert any("ACTION_CONFLICT" in r for r in res.rejection_reasons)


def test_insufficient_amr_rejected():
    """Kiểm tra REASSIGN_AMR bị reject khi không đủ xe AMR khả dụng trên R2."""
    # Tạo mock current_state với R2 không có xe nào available hoặc pin < 20
    curr_data = [
        {"entity_type": "RESOURCE", "entity_id": "AMR04", "metric": "route_id", "value": "R2"},
        {"entity_type": "RESOURCE", "entity_id": "AMR04", "metric": "available", "value": "0"},
        {"entity_type": "RESOURCE", "entity_id": "AMR04", "metric": "battery_pct", "value": "15.0"},
        {"entity_type": "RESOURCE", "entity_id": "AMR05", "metric": "route_id", "value": "R2"},
        {"entity_type": "RESOURCE", "entity_id": "AMR05", "metric": "available", "value": "0"},
        {"entity_type": "RESOURCE", "entity_id": "AMR05", "metric": "battery_pct", "value": "10.0"},
    ]
    curr_df = pd.DataFrame(curr_data)

    act = Action(
        action_id="A_REASSIGN",
        action_type="REASSIGN_AMR",
        parameters={"from_route": "R2", "to_route": "R1", "count": 1},
    )
    sc = Scenario(scenario_id="S_TEST", actions=[act], cause_coverage=[])
    res = check_static_feasibility(sc, current_state_df=curr_df)
    assert not res.is_feasible
    assert any("INSUFFICIENT_AVAILABLE_AMR" in r for r in res.rejection_reasons)


def test_scenario_generator_s0_always_present_and_max_scenarios():
    """Kiểm tra S0 luôn có mặt và tổng số kịch bản không vượt quá 8."""
    causes = [
        Cause(cause_type="DEMAND_SPIKE", contribution="high", evidence={}),
        Cause(cause_type="AMR_AVAILABILITY_DROP", contribution="high", evidence={}),
        Cause(cause_type="BUFFER_LOW", contribution="medium", evidence={}),
    ]
    scenarios = generate_scenarios(causes, max_scenarios=8)

    # 1. S0 luôn có mặt ở đầu
    assert len(scenarios) > 0
    assert scenarios[0].scenario_id == "S0"
    assert len(scenarios[0].actions) == 0

    # 2. Không vượt quá max_scenarios
    assert len(scenarios) <= 8

    # 3. Mọi kịch bản trả về đều phải khả thi
    for sc in scenarios:
        res = check_static_feasibility(sc)
        assert res.is_feasible
