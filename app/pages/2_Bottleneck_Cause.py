"""Explain bottleneck timing, triggering rules and diagnosed causes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app.Home import bootstrap, require_result
from app.presentation import (CAUSES, RULES, SEVERITIES, evidence_table, time_text)


result, _ = bootstrap("Điểm nghẽn và nguyên nhân")
require_result(result)
if not result.bottlenecks:
    st.success("Không phát hiện bottleneck; không cần can thiệp.")
for event in result.bottlenecks:
    with st.container(border=True):
        st.subheader(f"Tuyến {event.location} · {SEVERITIES.get(event.severity, event.severity)}")
        when, lead, risk = st.columns([2.4, 1, 1])
        when.metric("Dự báo lúc", time_text(event.predicted_time))
        lead.metric("Còn (phút)", event.lead_time_min)
        risk.metric("Rủi ro / 100", round(event.risk_score, 1))
        st.write("**Vì sao hệ thống báo nghẽn?** " + "; ".join(
            RULES.get(rule, rule) for rule in event.triggered_rules) + ".")
        with st.expander("Xem số liệu dùng để phát hiện", expanded=False):
            st.dataframe(evidence_table(event.evidence), hide_index=True,
                         use_container_width=True)

st.subheader("Nguyên nhân được chẩn đoán")
if not result.causes:
    st.info("Chưa xác định được nguyên nhân cụ thể.")
for cause in result.causes:
    with st.container(border=True):
        st.write(f"**{CAUSES.get(cause.cause_type, cause.cause_type)}** "
                 f"· Mức đóng góp: {SEVERITIES.get(cause.contribution, cause.contribution)}")
        st.dataframe(evidence_table(cause.evidence), hide_index=True,
                     use_container_width=True)
