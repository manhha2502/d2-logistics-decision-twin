"""
environment.py — SimPy environment + resources (Task 2).

All capacities come from master CSV / current state / YAML:
  * Picker           simpy.PriorityResource  (station_master, type "Picking")
  * Staging per route simpy.Container         (route_master.staging_capacity_totes)
  * Line buffer per material simpy.Container  (material_master.buffer_capacity_totes,
        else station "Line-side Buffer" capacity split evenly)
  * AMR pools        plain state objects, dispatched by processes.dispatch()
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import simpy

from .entities import AMR, LineBuffer, MaterialRequest, Picker, Route, StagingArea


class SimulationEnvironment:
    def __init__(self, env: simpy.Environment, sys_cfg: Dict[str, Any], thr_cfg: Dict[str, Any]):
        self.env = env
        self.sys_cfg = sys_cfg
        self.thr_cfg = thr_cfg

        self.amrs: Dict[str, AMR] = {}
        self.routes: Dict[str, Route] = {}
        self.picker: Picker | None = None
        self.staging: Dict[str, StagingArea] = {}
        self.line_buffers: Dict[str, LineBuffer] = {}

        self.ready: Dict[str, List[MaterialRequest]] = {}   # staged, waiting for an AMR
        self.backlog: Dict[str, float] = {}                  # totes released, not yet picked up
        self.initial_backlog: Dict[str, float] = {}          # queue_end_totes from current state

        self.conditions = None      # FutureConditions, set by simulator
        self.actions = None         # ActionPlan, set by actions.apply_actions
        self.metrics = None         # SimulationMetrics
        self.reassign_log: list = []

    # ------------------------------------------------------------------
    def load_from_master(
        self,
        resource_df: pd.DataFrame,
        route_df: pd.DataFrame,
        station_df: pd.DataFrame,
        current_state_df: pd.DataFrame,
        material_df: pd.DataFrame | None = None,
    ) -> None:
        routes_cfg = self.sys_cfg["routes"]

        for _, row in route_df.iterrows():
            rid = str(row["route_id"])
            self.routes[rid] = Route(
                route_id=rid,
                distance_m=float(row["distance_m"]),
                base_loaded_travel_min=float(row["base_loaded_travel_min"]),
                base_empty_travel_min=float(row["base_empty_travel_min"]),
                staging_capacity_totes=float(row["staging_capacity_totes"]),
                origin=str(row.get("origin", "")),
                destination=str(row.get("destination", "")),
            )
            cap = self.routes[rid].staging_capacity_totes
            self.staging[rid] = StagingArea(rid, cap, simpy.Container(self.env, capacity=cap))
            self.ready[rid] = []
            self.backlog[rid] = 0.0
            q0 = self._metric(current_state_df, "ROUTE", rid, "queue_end_totes", 0.0)
            self.initial_backlog[rid] = max(0.0, q0)

        # ---- picker --------------------------------------------------
        picker_id = routes_cfg["picker_station"]
        prow = station_df[station_df["station_id"] == picker_id]
        if prow.empty:
            raise ValueError(f"Picker station {picker_id!r} not found in station_master")
        override = (self.sys_cfg.get("simulation") or {}).get("picker_capacity")
        pcap = int(override) if override else int(prow.iloc[0]["capacity"])
        self.picker = Picker(picker_id, pcap, simpy.PriorityResource(self.env, capacity=pcap))

        # ---- line buffers per material --------------------------------
        materials = (
            [str(m) for m in material_df["material_id"]] if material_df is not None
            else [m for m in current_state_df.loc[current_state_df["entity_type"] == "BUFFER", "entity_id"].unique()]
        )
        buf_station = station_df[station_df["station_id"] == routes_cfg["line_buffer_station"]]
        station_cap = float(buf_station.iloc[0]["capacity"]) if not buf_station.empty else None
        for m in materials:
            cap = None
            if material_df is not None and "buffer_capacity_totes" in material_df.columns:
                cap = float(material_df.loc[material_df["material_id"] == m, "buffer_capacity_totes"].iloc[0])
            if cap is None:
                if station_cap is None:
                    raise ValueError("No buffer capacity: need material_master.buffer_capacity_totes or the line buffer station")
                cap = station_cap / len(materials)
            init = min(cap, max(0.0, self._metric(current_state_df, "BUFFER", m, "current_level_totes", 0.0)))
            self.line_buffers[m] = LineBuffer(m, cap, simpy.Container(self.env, capacity=cap, init=init))

        # ---- AMRs ---------------------------------------------------------
        default_min_batt = float(self.thr_cfg.get("simulation", {}).get("min_dispatch_battery_pct", 20.0))
        for _, row in resource_df.iterrows():
            if row["resource_type"] != "AMR":
                continue
            aid = str(row["resource_id"])
            home = str(row["home_route"])
            cur_route = current_state_df.loc[
                (current_state_df["entity_type"] == "RESOURCE") & (current_state_df["entity_id"] == aid)
                & (current_state_df["metric"] == "route_id"), "value"]
            route = str(cur_route.iloc[0]) if not cur_route.empty and str(cur_route.iloc[0]) in self.routes else home
            battery = self._metric(current_state_df, "RESOURCE", aid, "battery_pct", 100.0)
            avail_raw = self._metric(current_state_df, "RESOURCE", aid, "available", 1.0)
            min_batt = float(row["min_dispatch_battery_pct"]) if "min_dispatch_battery_pct" in resource_df.columns \
                and pd.notna(row.get("min_dispatch_battery_pct")) else default_min_batt
            amr = AMR(aid, route, float(row["payload_totes"]), True, battery, home_route=home)
            amr.set_available(0.0, bool(int(avail_raw)) and battery >= min_batt)
            amr.base_available = amr.available
            self.amrs[aid] = amr

    # ------------------------------------------------------------------
    @staticmethod
    def _metric(df: pd.DataFrame, entity_type: str, entity_id: str, metric: str, default: float) -> float:
        mask = (df["entity_type"] == entity_type) & (df["entity_id"] == entity_id) & (df["metric"] == metric)
        rows = df.loc[mask, "value"]
        if rows.empty:
            return default
        try:
            return float(rows.iloc[0])
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------
    def amr_ids_by_route(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for a in self.amrs.values():
            out.setdefault(a.home_route, []).append(a.amr_id)
        return out
