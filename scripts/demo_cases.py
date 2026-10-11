"""Run the five D2 acceptance cases with real modules and explicit input stresses.

The default Streamlit run uses the bundled PEAK snapshot unchanged. These cases
are synthetic demonstrations: changes to inputs are declared in demo_cases.yaml;
forecast values, states, SimPy KPIs, and recommendations are computed at run time.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.config import load_config
from src.common.schemas import QuantileValue
from src.forecast import service as forecast_service
from src.logistics.future_state import build_future_states
from src.bottleneck.detector import detect_bottlenecks
from src.bottleneck.cause_diagnosis import diagnose_bottlenecks
from src.simulation.simulator import run_simulation
from src.orchestration.pipeline import _execute


def run_case(name: str, settings: dict, folder: Path):
    """Return a real PipelineResult after applying only the declared inputs."""
    config = deepcopy(load_config())
    current = pd.read_csv(config["paths"]["current_state"])
    events = pd.read_csv(config["paths"]["known_events"])
    if settings.get("clear_known_events"):
        events = events.iloc[:0]
    if amr := settings.get("move_amr_to_r1"):
        mask = ((current.entity_type == "RESOURCE") & (current.entity_id == amr)
                & (current.metric == "route_id"))
        if mask.sum() != 1:
            raise ValueError(f"Unknown AMR in demo input: {amr}")
        current.loc[mask, "value"] = "R1"
    if settings.get("clear_r1_queue"):
        mask = ((current.entity_type == "ROUTE") & (current.entity_id == "R1")
                & (current.metric == "queue_end_totes"))
        current.loc[mask, "value"] = "0"
    if "buffer_level_mat_a" in settings:
        mask = ((current.entity_type == "BUFFER") & (current.entity_id == "MAT_A")
                & (current.metric == "current_level_totes"))
        current.loc[mask, "value"] = str(settings["buffer_level_mat_a"])
    if "r2_simulated_demand_totes_per_window" in settings:
        sim = config["system"]["simulation"]
        sim["calibrate_from_history"] = False
        sim["baseline_demand_r2"] = float(settings["r2_simulated_demand_totes_per_window"])
    current_path, events_path = folder / f"{name}_current.csv", folder / f"{name}_events.csv"
    current.to_csv(current_path, index=False)
    events.to_csv(events_path, index=False)
    config["paths"].update(current_state=current_path, known_events=events_path)

    multiplier = float(settings.get("forecast_demand_multiplier", 1.0))
    if multiplier <= 0:
        raise ValueError("forecast_demand_multiplier must be positive")

    def forecast_with_declared_stress(now, horizon_min, interval_min):
        points = forecast_service.forecast_future_drivers(now, horizon_min, interval_min)
        if multiplier == 1.0:
            return points
        return [replace(point, demand=QuantileValue(
            point.demand.p10 * multiplier,
            point.demand.p50 * multiplier,
            point.demand.p90 * multiplier,
        )) for point in points]

    services = {
        "forecast": forecast_with_declared_stress,
        "future_state": build_future_states,
        "bottleneck": detect_bottlenecks,
        "diagnose": diagnose_bottlenecks,
        "simulate": run_simulation,
    }
    with patch.object(forecast_service, "load_config", return_value=config):
        return _execute(config, services=services)


def main():
    cases = yaml.safe_load((ROOT / "config/demo_cases.yaml").read_text(encoding="utf-8"))["cases"]
    with TemporaryDirectory() as directory:
        for name, settings in cases.items():
            result = run_case(name, settings, Path(directory))
            chosen = (result.decision_package.recommended_scenario.scenario_id
                      if result.decision_package else "none")
            print(f"{name}: {result.status}; bottlenecks={len(result.bottlenecks)}; "
                  f"causes={[cause.cause_type for cause in result.causes]}; "
                  f"scenarios={len(result.scenarios)}; recommended={chosen}; "
                  f"rejected={result.rejected_scenarios}")


if __name__ == "__main__":
    main()
