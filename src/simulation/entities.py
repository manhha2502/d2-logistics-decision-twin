"""
entities.py — Internal dataclasses for the SimPy module (Task 1).

Capacities / payloads / times are filled from master CSV + YAML by
environment.py; nothing here is scenario- or demo-specific.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AMR:
    """Autonomous Mobile Robot state during simulation."""
    amr_id: str
    route: str                       # current route (REASSIGN_AMR may change it)
    payload_totes: float             # max totes per trip
    available: bool = True           # False = maintenance / low battery
    battery_pct: float = 100.0
    home_route: str = ""
    base_available: bool = True      # availability from current state (before known events)
    busy_time: float = 0.0           # cumulative minutes on trips (clipped to horizon)
    on_trip: bool = False
    trip_start: Optional[float] = None
    trip_route: str = ""
    unavailable_since: Optional[float] = None
    unavailable_time: float = 0.0    # cumulative minutes not available

    def set_available(self, now: float, flag: bool) -> None:
        """Change availability and keep the unavailable-time ledger."""
        if flag and not self.available:
            if self.unavailable_since is not None:
                self.unavailable_time += now - self.unavailable_since
            self.unavailable_since = None
        elif not flag and self.available:
            self.unavailable_since = now
        self.available = flag


@dataclass
class MaterialRequest:
    """One replenishment request placed by a production area.

    created_at  = time the material is *needed* (demand time, KPI reference)
    release_at  = time the request enters the system (<= created_at when
                  ADJUST_REPLENISHMENT_TIME pulls replenishment forward)
    """
    request_id: str
    material_id: str
    quantity_totes: float
    route: str
    created_at: float
    release_at: float = 0.0
    priority: int = 1
    noise: float = 1.0               # seeded multiplicative noise on process times
    staged_at: Optional[float] = None
    served_at: Optional[float] = None      # AMR pickup time
    completed_at: Optional[float] = None   # unloaded at destination
    initial_backlog: bool = False


@dataclass
class Route:
    route_id: str
    distance_m: float
    base_loaded_travel_min: float
    base_empty_travel_min: float
    staging_capacity_totes: float
    origin: str = ""
    destination: str = ""


@dataclass
class Picker:
    station_id: str
    capacity: int
    resource: Any = None             # simpy.PriorityResource


@dataclass
class StagingArea:
    route_id: str
    capacity: float
    container: Any = None            # simpy.Container


@dataclass
class LineBuffer:
    material_id: str
    capacity: float
    container: Any = None            # simpy.Container


@dataclass
class ProductionLine:
    line_id: str
    materials: list[str] = field(default_factory=list)
