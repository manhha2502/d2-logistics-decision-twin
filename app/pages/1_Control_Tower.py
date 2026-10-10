import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dataclasses import asdict
import pandas as pd
import plotly.express as px
import streamlit as st
from app.Home import bootstrap, require_result
from app.theme import plotly_chart

result, _ = bootstrap("Control Tower")
require_result(result)
st.subheader(f"Now · {result.now}")
st.dataframe(result.current_state.pivot(index=["entity_type", "entity_id"], columns="metric", values="value"), use_container_width=True)
states = pd.DataFrame([asdict(s) for s in result.future_states])
states["Horizon"] = states["timestamp"].map(lambda t: f"+{int((t-result.now).total_seconds()/60)} min")
st.subheader("+15 / +30 / +45 / +60")
st.dataframe(states, hide_index=True, use_container_width=True)
forecasts = pd.DataFrame([{"timestamp": f.timestamp, "P10": f.demand.p10, "P50": f.demand.p50, "P90": f.demand.p90} for f in result.forecasts])
plotly_chart(px.line(forecasts, x="timestamp", y=["P10", "P50", "P90"], markers=True, title="Demand R1 · totes / 15 min"))
for metrics, title in ((["demand", "capacity"], "Demand / Capacity"),
                       (["queue_end", "waiting_time"], "Queue (totes) / Waiting (min)"),
                       (["buffer_mat_a", "buffer_mat_b"], "MAT_A / MAT_B buffer (totes)"),
                       (["amr_available"], "AMR available")):
    plotly_chart(px.line(states, x="timestamp", y=metrics, color="location", markers=True, title=title))
if result.bottlenecks:
    risks = pd.DataFrame([{"timestamp": b.predicted_time, "location": b.location, "risk_score": b.risk_score, "severity": b.severity} for b in result.bottlenecks])
    plotly_chart(px.scatter(risks, x="timestamp", y="risk_score", color="location", symbol="severity", title="Risk timeline · detected events (0–100)"))
else:
    st.success("Không phát hiện bottleneck trong 60 phút tới.")
st.subheader("Travel / Process forecast R1")
st.dataframe(pd.DataFrame([{"timestamp": f.timestamp, "driver": driver,
    "P10": getattr(f, driver).p10, "P50": getattr(f, driver).p50, "P90": getattr(f, driver).p90}
    for f in result.forecasts for driver in ("travel_loaded", "travel_empty", "picking_time", "loading_time", "unloading_time")]), hide_index=True)
