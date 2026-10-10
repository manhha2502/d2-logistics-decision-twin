import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import streamlit as st
from app.Home import bootstrap, require_result

result, _ = bootstrap("Bottleneck & Cause")
require_result(result)
for event in result.bottlenecks:
    with st.container(border=True):
        st.subheader(f"{event.location} · {event.severity}")
        columns = st.columns(3)
        columns[0].metric("When", str(event.predicted_time))
        columns[1].metric("Lead time (min)", event.lead_time_min)
        columns[2].metric("Risk (0–100)", event.risk_score)
        st.write("Triggered rules", ", ".join(event.triggered_rules))
        st.write("Evidence · demand / capacity / AMR / travel / queue / buffer")
        st.json(event.evidence)
st.subheader("Cause diagnosis · rule-based")
for cause in result.causes:
    with st.container(border=True):
        st.write(f"**{cause.cause_type}** · contribution: {cause.contribution}")
        st.json(cause.evidence)
