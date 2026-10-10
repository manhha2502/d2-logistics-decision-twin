"""Transport capacity calculations for a fixed planning window."""

from __future__ import annotations


def calculate_transport_capacity(
    amr_available: int,
    payload_totes: float,
    load_factor: float = 1.0,
    window_min: float = 15.0,
    loading_time: float = 0.0,
    travel_loaded: float = 0.0,
    unloading_time: float = 0.0,
    travel_empty: float = 0.0,
    **aliases: float,
) -> float:
    """Return tote capacity in ``window_min``.

    A trip is a complete loading/loaded-travel/unloading/empty-return cycle.
    Fractional capacity is intentionally retained because the future-state model
    operates on aggregate 15-minute buckets.
    """
    loading_time = float(aliases.get("loading_min", loading_time))
    travel_loaded = float(aliases.get("loaded_travel_min", travel_loaded))
    unloading_time = float(aliases.get("unloading_min", unloading_time))
    travel_empty = float(aliases.get("empty_travel_min", travel_empty))
    cycle_time = loading_time + travel_loaded + unloading_time + travel_empty
    values = (amr_available, payload_totes, load_factor, window_min, cycle_time)
    if any(float(value) < 0 for value in values):
        raise ValueError("capacity inputs must be non-negative")
    if cycle_time == 0 or amr_available == 0 or window_min == 0:
        return 0.0
    if load_factor > 1:
        raise ValueError("load_factor must be between 0 and 1")
    return float(amr_available) * float(payload_totes) * float(load_factor) * float(window_min) / cycle_time
