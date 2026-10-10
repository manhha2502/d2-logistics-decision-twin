"""Bounded line-buffer accounting."""

from __future__ import annotations


def update_buffer(
    current_level: float,
    delivery: float,
    consumption: float,
    max_capacity: float,
) -> dict[str, float]:
    """Apply a delivery and consumption while preserving buffer bounds."""
    if min(current_level, delivery, consumption, max_capacity) < 0:
        raise ValueError("buffer inputs must be non-negative")
    if current_level > max_capacity:
        raise ValueError("current_level cannot exceed max_capacity")
    accepted_delivery = min(float(delivery), float(max_capacity) - float(current_level))
    overflow = max(0.0, float(delivery) - accepted_delivery)
    available = float(current_level) + accepted_delivery
    actual_consumption = min(float(consumption), available)
    return {
        "accepted_delivery": accepted_delivery,
        "consumption": actual_consumption,
        "next_level": max(0.0, min(float(max_capacity), available - actual_consumption)),
        "unmet_consumption": max(0.0, float(consumption) - actual_consumption),
        "overflow": overflow,
    }
