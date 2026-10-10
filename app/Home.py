"""Streamlit entry point and shared controls for all dashboard pages."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import asdict
from datetime import datetime
import pandas as pd
import streamlit as st
from app.theme import initialize_theme
from src.common.config import load_config, ConfigError
from src.orchestration.pipeline import (run_pipeline, module_readiness, save_run,
                                         record_operator_decision, PipelineError)


def bootstrap(title):
    """Initialize a page and return the last successful run and configuration."""
    st.set_page_config(page_title=f"D2 · {title}", page_icon="🏭", layout="wide")
    initialize_theme(title)
    try:
        config = load_config()
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()
    with st.sidebar:
        st.header("D2 Decision Twin")
        st.caption("LINE_A · R1 / R2 · 60 phút · dữ liệu synthetic PEAK v2")
        with st.form("run_settings"):
            modes = list(config["decision"]["decision_modes"])
            mode = st.selectbox("Decision mode", modes,
                index=modes.index(config["system"]["default_decision_mode"]))
            snapshot = st.text_input("Thời điểm snapshot", str(config["system"]["snapshot_time"]))
            seed = st.number_input("Seed", value=config["system"]["seed"], step=1)
            run = st.form_submit_button("Run Decision Twin", type="primary")
        st.caption("Thời điểm mặc định khớp snapshot CSV. Đổi thời điểm cần cập nhật dữ liệu tương ứng.")
        missing = module_readiness() + config["readiness_warnings"]
        if missing:
            with st.expander("Module chưa sẵn sàng", expanded=True):
                for message in missing:
                    st.warning(message)
        rerun = st.button("RUN AGAIN", use_container_width=True)
        if run or rerun:
            # Clear old output on failure so it cannot be mistaken for this run.
            st.session_state.pop("pipeline_result", None)
            try:
                timestamp = datetime.fromisoformat(snapshot)
                if missing:
                    raise PipelineError("Chưa thể chạy pipeline thật:\n" + "\n".join(missing))
                with st.spinner("Forecast → Bottleneck → Simulation → Recommendation…"):
                    result = run_pipeline(mode, timestamp, int(seed))
                    save_run(result, config)
                st.session_state["pipeline_result"] = result
                st.success("Đã hoàn thành pipeline")
            except Exception as exc:
                st.error(f"Không thể hoàn thành: {exc}")
    result = st.session_state.get("pipeline_result")
    if result:
        st.caption(f"Run {result.run_id[:12]} · {result.now} · {result.decision_mode} · seed {result.seed}")
        if result.status == "No intervention required":
            st.success(result.status)
        else:
            st.info(result.status)
    return result, config


def require_result(result):
    if result is None:
        st.info("Chọn cấu hình và bấm Run Decision Twin ở thanh bên để xem kết quả.")
        st.stop()


def scenario_table(result):
    """Table always places baseline first and includes rejected scenarios."""
    rows = []
    for scenario in sorted(result.scenarios, key=lambda s: (s.scenario_id != "S0", s.scenario_id)):
        sim = result.simulation_results.get(scenario.scenario_id)
        row = {"Scenario": scenario.scenario_id,
               "Actions": ", ".join(a.action_type for a in scenario.actions) or "No Action",
               "Status": "; ".join(result.rejected_scenarios.get(scenario.scenario_id, [])) or "Feasible",
               "Robustness": result.robustness.get(scenario.scenario_id, {}).get("rating", "Not tested")}
        if sim:
            row.update({"Waiting (min)": sim.avg_waiting_time, "Queue": sim.avg_queue,
                        "Late": sim.late_delivery_count, "Starvation (min)": sim.starvation_minutes,
                        "Throughput": sim.throughput, "Service Level": sim.service_level,
                        "Unmet": sim.unmet_consumption, "Overflow": sim.buffer_overflow,
                        "Secondary Bottleneck": sim.secondary_bottleneck})
        rows.append(row)
    return pd.DataFrame(rows)


def render_recommendation(result, config):
    require_result(result)
    package = result.decision_package
    if package is None:
        st.info("Không cần can thiệp; không chạy mô phỏng.")
        return
    scenario = package.recommended_scenario
    st.subheader(f"Recommended Scenario: {scenario.scenario_id}")
    if scenario.actions:
        st.dataframe(pd.DataFrame([{"Action": a.action_type, **a.parameters} for a in scenario.actions]), hide_index=True)
    else:
        st.write("No Action")
    b = package.bottleneck
    st.write(f"{b.location} · {b.predicted_time} · {b.severity} · Lead time {b.lead_time_min} phút · Risk {b.risk_score:.1f}")
    st.subheader("KPI: S0 → Recommended")
    st.dataframe(pd.DataFrame([{"Scenario": "S0", **asdict(package.baseline_result)},
                              {"Scenario": scenario.scenario_id, **asdict(package.recommended_result)}]), hide_index=True)
    st.write("Mức cải thiện so với S0")
    st.json(package.kpi_improvement)
    st.write("Tác dụng phụ và thời gian thực hiện")
    st.json(package.side_effects)
    st.write("Robustness: P10 / P50 / P90")
    st.json(package.robustness)
    st.caption("Quyết định của operator chỉ được ghi vào CSV; hệ thống không điều khiển AMR thật. MODIFY ghi yêu cầu thay đổi để chạy lại.")
    with st.form("operator_decision"):
        notes = st.text_area("Ghi chú / nội dung cần sửa")
        columns = st.columns(3)
        approve = columns[0].form_submit_button("APPROVE", type="primary")
        modify = columns[1].form_submit_button("MODIFY")
        reject = columns[2].form_submit_button("REJECT")
    if approve or modify or reject:
        decision = "APPROVE" if approve else "MODIFY" if modify else "REJECT"
        try:
            path = record_operator_decision(result, decision, notes, config)
            st.success(f"Đã ghi {decision}: {path.name}")
        except (ValueError, OSError) as exc:
            st.error(str(exc))


def main():
    result, config = bootstrap("D2 Logistics Decision Twin")
    st.write("Dự báo rủi ro logistics và so sánh phương án can thiệp trước khi operator quyết định.")
    st.write("Input → Forecast → Future State → Bottleneck → Cause → Scenario → SimPy → Evaluation → Robustness → Recommendation")
    for path, label in (("pages/1_Control_Tower.py", "Control Tower"),
                        ("pages/2_Bottleneck_Cause.py", "Bottleneck & Cause"),
                        ("pages/3_Scenario_Comparison.py", "Scenario Comparison"),
                        ("pages/4_Recommendation.py", "Recommendation")):
        st.page_link(path, label=label)
    if result:
        st.dataframe(scenario_table(result), hide_index=True, use_container_width=True)


if __name__ == "__main__":
    main()
