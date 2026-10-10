import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd
import streamlit as st
from app.Home import bootstrap, require_result, scenario_table

result, _ = bootstrap("Scenario Comparison")
require_result(result)
st.dataframe(scenario_table(result), hide_index=True, use_container_width=True)
if result.rejected_scenarios:
    st.subheader("Phương án bị loại")
    st.json(result.rejected_scenarios)
if result.ranked_scenarios:
    st.subheader("Xếp hạng sau constraints + Pareto")
    st.dataframe(pd.DataFrame(result.ranked_scenarios, columns=["Scenario", "Score"]), hide_index=True)
if result.kpi_comparison:
    with st.expander("KPI improvement vs S0 (%)"):
        st.dataframe(pd.DataFrame.from_dict(result.kpi_comparison, orient="index"))
for condition, results in result.results_by_condition.items():
    with st.expander(f"{condition} · simulation results"):
        from dataclasses import asdict
        st.dataframe(pd.DataFrame([asdict(r) for r in results.values()]), hide_index=True)
st.caption("Not tested = phương án không nằm trong top robustness; không suy đoán kết quả P10/P90.")
