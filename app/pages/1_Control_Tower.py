"""Snapshot and 60-minute forecast in operator-facing units."""
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import plotly.express as px
import streamlit as st

from app.Home import bootstrap, require_result
from app.presentation import FIELDS, SEVERITIES, time_text
from app.theme import plotly_chart


def trend(frame, value, title, unit):
    fig = px.line(frame, x="timestamp", y=value, color="location", markers=True,
                  title=title, labels={"timestamp": "Thời điểm", value: unit,
                                       "location": "Tuyến"}, height=360)
    fig.update_xaxes(tickformat="%H:%M")
    fig.update_layout(legend_title_text="Tuyến")
    plotly_chart(fig)


result, _ = bootstrap("Tổng quan vận hành")
require_result(result)
st.subheader(f"Dữ liệu hiện tại · {time_text(result.now)}")
current = result.current_state.pivot(index=["entity_type", "entity_id"],
                                     columns="metric", values="value").reset_index()
for entity_type, title, columns in (
    ("ROUTE", "Tuyến vận chuyển", ["entity_id", "queue_end_totes", "dcr", "utilization"]),
    ("RESOURCE", "Xe AMR", ["entity_id", "route_id", "available", "battery_pct", "status"]),
    ("BUFFER", "Buffer vật tư", ["entity_id", "current_level_totes", "fill_ratio"]),
):
    subset = current.loc[current.entity_type == entity_type]
    if not subset.empty:
        subset = subset.copy()
        if entity_type == "RESOURCE":
            subset["available"] = subset["available"].replace({"1": "Có", "0": "Không"})
            subset["status"] = subset["status"].replace({"idle": "Đang chờ", "busy": "Đang hoạt động"})
        if entity_type == "ROUTE":
            subset["utilization"] = subset["utilization"].map(
                lambda value: f"{float(value) * 100:.1f}%")
        if entity_type == "BUFFER":
            subset["fill_ratio"] = subset["fill_ratio"].map(
                lambda value: f"{float(value) * 100:.1f}%")
        st.write(f"**{title}**")
        st.dataframe(subset[[column for column in columns if column in subset]].rename(columns=FIELDS),
                     hide_index=True, use_container_width=True)

states = pd.DataFrame([asdict(state) for state in result.future_states])
states["Sau hiện tại"] = states["timestamp"].map(
    lambda value: f"+{int((value-result.now).total_seconds()/60)} phút")
st.subheader("Dự báo trong 60 phút tới")
overview = ["Sau hiện tại", "timestamp", "location", "demand", "capacity",
            "queue_end", "waiting_time", "amr_available"]
st.dataframe(states[overview].rename(columns=FIELDS), hide_index=True,
             use_container_width=True)

forecast = pd.DataFrame([{"timestamp": point.timestamp,
                          "Nhu cầu thấp (P10)": point.demand.p10,
                          "Nhu cầu kỳ vọng (P50)": point.demand.p50,
                          "Nhu cầu cao (P90)": point.demand.p90}
                         for point in result.forecasts])
st.subheader("Nhu cầu dự báo của R1")
fig = px.line(forecast, x="timestamp", y=list(forecast.columns[1:]), markers=True,
              title="Nhu cầu R1 theo ba mức dự báo", height=360,
              labels={"timestamp": "Thời điểm", "value": "Tote / 15 phút", "variable": "Mức dự báo"})
fig.update_xaxes(tickformat="%H:%M")
fig.update_layout(legend_title_text="Mức dự báo")
plotly_chart(fig)

st.subheader("Nhu cầu so với năng lực")
capacity = states.melt(id_vars=["timestamp", "location"], value_vars=["demand", "capacity"],
                       var_name="Chỉ số", value_name="Tote / 15 phút")
capacity["Đường"] = capacity["location"] + " · " + capacity["Chỉ số"].map(
    {"demand": "Nhu cầu", "capacity": "Năng lực"})
fig = px.line(capacity, x="timestamp", y="Tote / 15 phút", color="Đường",
              markers=True, title="Nhu cầu và năng lực theo tuyến", height=360,
              labels={"timestamp": "Thời điểm"})
fig.update_xaxes(tickformat="%H:%M")
plotly_chart(fig)

st.subheader("Hàng đợi và thời gian chờ")
trend(states, "queue_end", "Hàng đợi cuối mỗi khoảng 15 phút", "Tote")
trend(states, "waiting_time", "Thời gian chờ dự báo", "Phút")

st.subheader("Vật tư và AMR")
for field, title, unit in (
    ("buffer_mat_a", "Tồn buffer MAT_A", "Tote"),
    ("buffer_mat_b", "Tồn buffer MAT_B", "Tote"),
    ("amr_available", "AMR sẵn sàng", "Số AMR"),
):
    trend(states, field, title, unit)

if result.bottlenecks:
    st.subheader("Thời điểm dự báo có bottleneck")
    risks = pd.DataFrame([{"timestamp": event.predicted_time, "location": event.location,
                           "risk_score": event.risk_score,
                           "severity": SEVERITIES.get(event.severity, event.severity)}
                          for event in result.bottlenecks])
    fig = px.scatter(risks, x="timestamp", y="risk_score", color="location",
                     symbol="severity", title="Rủi ro bottleneck theo thời gian", height=360,
                     labels={"timestamp": "Thời điểm", "risk_score": "Điểm rủi ro (0–100)",
                             "location": "Tuyến", "severity": "Mức độ"})
    fig.update_xaxes(tickformat="%H:%M")
    plotly_chart(fig)
else:
    st.success("Không phát hiện bottleneck trong 60 phút tới.")

with st.expander("Xem chi tiết thời gian di chuyển và xử lý ở R1"):
    details = pd.DataFrame([
        {"Thời điểm": time_text(point.timestamp), "Công đoạn": FIELDS[driver],
         "P10": round(getattr(point, driver).p10, 2),
         "P50": round(getattr(point, driver).p50, 2),
         "P90": round(getattr(point, driver).p90, 2)}
        for point in result.forecasts
        for driver in ("travel_loaded", "travel_empty", "picking_time",
                       "loading_time", "unloading_time")])
    st.dataframe(details, hide_index=True, use_container_width=True)
