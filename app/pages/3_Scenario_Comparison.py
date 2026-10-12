"""Compare candidate interventions against the S0 baseline."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.Home import bootstrap, require_result, scenario_table, simulation_kpi_table
from app.presentation import CONDITIONS, IMPROVEMENTS, number_text, rejection_text


result, _ = bootstrap("So sánh phương án")
require_result(result)
st.subheader("Các phương án và kết quả mô phỏng kỳ vọng (P50)")
st.dataframe(scenario_table(result), hide_index=True, use_container_width=True)

if result.rejected_scenarios:
    st.subheader("Phương án không đạt ràng buộc")
    rows = [{"Phương án": scenario_id, "Lý do": rejection_text(reason)}
            for scenario_id, reasons in result.rejected_scenarios.items() for reason in reasons]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

if result.ranked_scenarios:
    st.subheader("Xếp hạng phương án còn lại")
    st.dataframe(pd.DataFrame([{"Phương án": scenario_id, "Điểm xếp hạng": round(score, 3)}
                               for scenario_id, score in result.ranked_scenarios]),
                 hide_index=True, use_container_width=True)

if result.kpi_comparison:
    with st.expander("Xem mức thay đổi của từng phương án so với S0"):
        rows = [{"Phương án": scenario_id, "Chỉ số": IMPROVEMENTS.get(metric, metric),
                 "Thay đổi": number_text(value) + ("" if metric == "disruption" else "%")}
                for scenario_id, metrics in result.kpi_comparison.items()
                if scenario_id != "S0" for metric, value in metrics.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

st.subheader("Thử trong các điều kiện khác nhau")
for condition, results in result.results_by_condition.items():
    with st.expander(f"{CONDITIONS.get(condition, condition)} · kết quả mô phỏng"):
        st.dataframe(simulation_kpi_table(results.values()), hide_index=True,
                     use_container_width=True)
