"""Queue evolution for an aggregate planning window."""

from __future__ import annotations


def calculate_queue_state(
    queue_start: float,
    demand: float,
    capacity: float,
    staging_capacity: float,
) -> dict[str, float]:
    """Calculate throughput, ending queue and staging overflow.

    Existing work is served before new demand, and no value returned is
    negative. Work beyond physical staging capacity is reported as overflow.
    """
    if min(queue_start, demand, capacity, staging_capacity) < 0:
        raise ValueError("queue inputs must be non-negative")
    available_work = float(queue_start) + float(demand)
    throughput = min(available_work, float(capacity))
    raw_queue = max(0.0, available_work - throughput)
    queue_end = min(raw_queue, float(staging_capacity))
    return {
        "throughput": throughput,
        "raw_queue": raw_queue,
        "queue_end": queue_end,
        "overflow": max(0.0, raw_queue - queue_end),
    }
