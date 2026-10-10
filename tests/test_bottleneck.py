from datetime import datetime

from src.bottleneck.detector import detect_bottlenecks
from src.bottleneck.hard_rules import evaluate_hard_rules, load_thresholds, trigger_hard_rules
from src.bottleneck.risk_score import calculate_risk_components, calculate_risk_score
from src.common.schemas import FutureState


def state(**changes):
    values = dict(
        timestamp=datetime(2026, 10, 8, 14, 15), location="R1", demand=12, capacity=10,
        dcr=1.2, throughput=10, queue_start=1, queue_end=3, waiting_time=5,
        utilization=1, buffer_mat_a=20, buffer_mat_b=18, unmet_consumption=0,
        overflow=0, amr_available=2,
    )
    values.update(changes)
    return FutureState(**values)


def test_all_risk_components_stay_in_range():
    score = calculate_risk_score(state(dcr=99, queue_end=999, waiting_time=999))
    assert 0 <= score <= 100


def test_threshold_loader_reads_yaml_config():
    config = load_thresholds()
    assert config["dcr"]["critical"] == 1.0
    assert config["risk"]["weights"]["dcr"] == 0.30


def test_risk_components_are_individually_normalized():
    components = calculate_risk_components(state(dcr=99, queue_end=999, waiting_time=999))
    assert set(components) == {"dcr", "queue_growth", "waiting", "utilization", "buffer"}
    assert all(0 <= value <= 1 for value in components.values())


def test_critical_hard_rule_overrides_score_severity():
    item = state(demand=1, capacity=10, dcr=.1, utilization=.1, queue_end=0,
                 waiting_time=0, buffer_mat_a=20, buffer_mat_b=18, unmet_consumption=1)
    event = detect_bottlenecks([item])[0]
    assert "UNMET_CONSUMPTION" in event.triggered_rules
    assert event.severity == "Critical"


def test_required_rules_trigger():
    rules = evaluate_hard_rules(state(buffer_mat_a=1, overflow=2))
    assert {"DCR_CRITICAL", "QUEUE_GROWTH", "HIGH_UTILIZATION", "CRITICAL_LOW_BUFFER", "BUFFER_OVERFLOW"} <= set(rules)


def test_rule_name_compatibility_api():
    names = trigger_hard_rules(state(buffer_mat_a=1, overflow=2))
    assert "DCR_CRITICAL" in names
    assert "CRITICAL_LOW_BUFFER" in names


def test_healthy_state_has_no_event():
    healthy = state(demand=2, capacity=10, dcr=.2, utilization=.2, queue_start=0,
                    queue_end=0, waiting_time=0, buffer_mat_a=20, buffer_mat_b=18)
    assert detect_bottlenecks([healthy]) == []


def test_r2_does_not_inherit_line_a_buffer_rules_or_risk():
    r2 = state(location="R2", buffer_mat_a=0, buffer_mat_b=0, unmet_consumption=0,
               demand=2, capacity=8, dcr=.25, queue_start=0, queue_end=0,
               throughput=2, waiting_time=0, utilization=.25)
    assert not any("BUFFER" in name for name in evaluate_hard_rules(r2))
    assert calculate_risk_components(r2)["buffer"] == 0


def test_staging_overflow_is_not_mislabeled_buffer_overflow():
    item = state(demand=20, throughput=10, queue_start=0, queue_end=2, overflow=8,
                 buffer_mat_a=20, buffer_mat_b=18)
    assert "BUFFER_OVERFLOW" not in evaluate_hard_rules(item)
    event = detect_bottlenecks([item])[0]
    assert event.evidence["queue_overflow"] == 8
    assert event.evidence["buffer_overflow"] == 0
