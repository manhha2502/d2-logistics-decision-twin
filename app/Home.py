"""Streamlit entry point and shared controls for all dashboard pages."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime
import pandas as pd
import streamlit as st
from app.presentation import (CONDITIONS, FIELDS, IMPROVEMENTS, MODE_NAMES, RATINGS,
                              action_text, action_timing, number_text,
                              rejection_text, time_text)
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
        with st.form("run_settings"):
            modes = list(config["decision"]["decision_modes"])
            previous = st.session_state.get("pipeline_result")
            if "decision_mode_selection" not in st.session_state:
                st.session_state["decision_mode_selection"] = (
                    previous.decision_mode if previous else config["system"]["default_decision_mode"]
                )
            mode = st.selectbox("Cách chọn phương án", modes,
                key="decision_mode_selection",
                format_func=lambda value: MODE_NAMES.get(value, value))
            snapshot = st.text_input(
                "Thời điểm dữ liệu hiện tại",
                str(config["system"]["snapshot_time"]),
            )
            seed = st.number_input("Seed (để lặp lại kết quả)", value=config["system"]["seed"], step=1)
            run = st.form_submit_button("Chạy phân tích", type="primary", width="stretch")
            rerun = st.form_submit_button("Chạy lại", width="stretch")
        missing = module_readiness() + config["readiness_warnings"]
        if missing:
            with st.expander("Module chưa sẵn sàng", expanded=True):
                for message in missing:
                    st.warning(message)
        if run or rerun:
            # Clear old output on failure so it cannot be mistaken for this run.
            st.session_state.pop("pipeline_result", None)
            try:
                timestamp = datetime.fromisoformat(snapshot)
                if missing:
                    raise PipelineError("Chưa thể chạy pipeline thật:\n" + "\n".join(missing))
                with st.spinner("Đang dự báo, tìm bottleneck và mô phỏng phương án…"):
                    result = run_pipeline(mode, timestamp, int(seed))
                    save_run(result, config)
                st.session_state["pipeline_result"] = result
                st.success("Đã hoàn thành phân tích")
            except Exception as exc:
                st.error(f"Không thể hoàn thành: {exc}")
    return st.session_state.get("pipeline_result"), config


def require_result(result):
    if result is None:
        st.info("Chọn cấu hình và bấm Chạy phân tích ở thanh bên để xem kết quả.")
        st.stop()


def scenario_table(result):
    """Table always places baseline first and includes rejected scenarios."""
    rows = []
    for scenario in sorted(result.scenarios, key=lambda s: (s.scenario_id != "S0", s.scenario_id)):
        sim = result.simulation_results.get(scenario.scenario_id)
        rejected = result.rejected_scenarios.get(scenario.scenario_id, [])
        rating = result.robustness.get(scenario.scenario_id, {}).get("rating")
        row = {"Phương án": scenario.scenario_id,
               "Hành động": "; ".join(action_text(a) for a in scenario.actions) or "Giữ nguyên hiện trạng",
               "Kết quả kiểm tra": "; ".join(map(rejection_text, rejected)) or "Có thể xem xét",
               "Độ ổn định": RATINGS.get(rating, "Chưa kiểm tra")}
        if sim:
            row.update({"Chờ TB (phút)": round(sim.avg_waiting_time, 2),
                        "Hàng đợi TB (tote)": round(sim.avg_queue, 2),
                        "Lượt giao trễ": sim.late_delivery_count,
                        "Tote xử lý": round(sim.throughput, 2),
                        "Mức đáp ứng (%)": round(sim.service_level * 100, 1),
                        "Nghẽn phụ R2": "Có" if sim.secondary_bottleneck else "Không"})
        rows.append(row)
    return pd.DataFrame(rows)


def simulation_kpi_table(simulations):
    """Display scalar SimPy KPIs without nested Arrow-incompatible metadata."""
    rows = []
    for simulation in simulations:
        rows.append({"Phương án": simulation.scenario_id,
                     "Chờ TB (phút)": round(simulation.avg_waiting_time, 2),
                     "Hàng đợi TB (tote)": round(simulation.avg_queue, 2),
                     "Lượt giao trễ": simulation.late_delivery_count,
                     "Tote xử lý": round(simulation.throughput, 2),
                     "Mức đáp ứng (%)": round(simulation.service_level * 100, 1),
                     "Thiếu vật tư (phút)": round(simulation.starvation_minutes, 2),
                     "Nghẽn phụ R2": "Có" if simulation.secondary_bottleneck else "Không"})
    return pd.DataFrame(rows)


def render_recommendation(result, config):
    require_result(result)
    package = result.decision_package
    if package is None:
        st.info("Không cần can thiệp; không chạy mô phỏng.")
        return
    scenario = package.recommended_scenario
    st.subheader(f"Đề xuất cho operator · {scenario.scenario_id}")
    if scenario.actions:
        for index, action in enumerate(scenario.actions, start=1):
            st.success(f"{index}. {action_text(action)} · {action_timing(action)}")
    else:
        if result.status == "No intervention preferred":
            st.info("Giữ nguyên S0 vì chế độ đang chọn xếp S0 cao hơn các can thiệp khả thi. Bạn có thể xem S1 ở trang So sánh phương án.")
        else:
            st.warning("Giữ phương án S0: chưa có can thiệp an toàn để đề xuất. Theo dõi tình trạng và đánh giá lại khi đầu vào thay đổi.")
    b = package.bottleneck
    st.write(f"**Vì sao?** Dự báo bottleneck tại **{b.location}** lúc **{time_text(b.predicted_time)}** "
             f"(còn {b.lead_time_min} phút; điểm rủi ro {b.risk_score:.1f}/100).")
    if package.causes:
        from app.presentation import CAUSES
        st.write("**Nguyên nhân được chẩn đoán:** " + ", ".join(
            CAUSES.get(cause.cause_type, cause.cause_type) for cause in package.causes))
    st.subheader("Kết quả mô phỏng so với S0 (giữ nguyên)")
    comparison = [package.baseline_result]
    if scenario.scenario_id != "S0":
        comparison.append(package.recommended_result)
    elif result.status == "No intervention preferred":
        alternative = next((scenario_id for scenario_id, _ in result.ranked_scenarios
                            if scenario_id != "S0"), None)
        if alternative:
            comparison.append(result.simulation_results[alternative])
    st.dataframe(simulation_kpi_table(comparison),
                 hide_index=True, use_container_width=True)
    improvement = [{"Chỉ số": IMPROVEMENTS.get(key, key),
                    "Thay đổi": number_text(value) + ("" if key == "disruption" else "%")}
                   for key, value in package.kpi_improvement.items()]
    with st.expander("Xem mức thay đổi so với S0"):
        st.dataframe(pd.DataFrame(improvement), hide_index=True, use_container_width=True)

    st.subheader("Điểm cần theo dõi")
    limits = config["decision"]["dynamic_constraints"]
    recommended = package.recommended_result
    baseline = package.baseline_result
    warnings = []
    if recommended.late_delivery_count > limits["max_late_delivery_count"]:
        warnings.append(f"Vẫn còn {recommended.late_delivery_count} lượt giao trễ "
                        f"(S0: {baseline.late_delivery_count}; ngưỡng: {limits['max_late_delivery_count']}).")
    overloaded = [name for name, value in recommended.amr_utilization.items()
                  if value > limits["max_amr_utilization"]]
    if overloaded:
        warnings.append("Mức sử dụng AMR vẫn trên ngưỡng: " + ", ".join(overloaded) + ".")
    for action in scenario.actions:
        if action.action_type == "REASSIGN_AMR":
            origin = action.parameters.get("from_route", "R2")
            warnings.append(f"Theo dõi hàng đợi và năng lực của {origin} khi tạm chuyển AMR đi.")
    for warning in warnings:
        st.warning(warning)
    if not warnings:
        st.success("Không có cảnh báo thêm từ kết quả mô phỏng.")

    robustness = package.robustness.get(scenario.scenario_id, {})
    if robustness:
        st.subheader("Độ ổn định qua ba điều kiện")
        rows = [{"Điều kiện": CONDITIONS[key], "Mức đáp ứng (%)": round(robustness[field] * 100, 1)}
                for key, field in (("favorable", "favorable_service_level"),
                                   ("expected", "expected_service_level"),
                                   ("adverse", "adverse_service_level")) if field in robustness]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        st.write("**Đánh giá:** " + RATINGS.get(robustness.get("rating"), "Chưa kiểm tra đủ"))

    with st.form("operator_decision"):
        notes = st.text_area("Ghi chú / nội dung cần sửa")
        columns = st.columns(3)
        approve = columns[0].form_submit_button("Chấp thuận", type="primary")
        modify = columns[1].form_submit_button("Yêu cầu sửa")
        reject = columns[2].form_submit_button("Từ chối")
    if approve or modify or reject:
        decision = "APPROVE" if approve else "MODIFY" if modify else "REJECT"
        try:
            path = record_operator_decision(result, decision, notes, config)
            st.success(f"Đã ghi quyết định vào {path.name}")
        except (ValueError, OSError) as exc:
            st.error(str(exc))


def main():
    result, config = bootstrap("D2 Logistics Decision Twin")
    links = (
        ("pages/1_Control_Tower.py", "Tổng quan vận hành", ":material/monitoring:"),
        ("pages/2_Bottleneck_Cause.py", "Điểm nghẽn và nguyên nhân", ":material/search:"),
        ("pages/3_Scenario_Comparison.py", "So sánh phương án", ":material/compare_arrows:"),
        ("pages/4_Recommendation.py", "Đề xuất hành động", ":material/task_alt:"),
    )
    for first, second in (links[:2], links[2:]):
        left, right = st.columns(2, gap="medium")
        for column, (path, label, icon) in zip((left, right), (first, second)):
            with column:
                st.page_link(path, label=label, icon=icon, width="stretch")
    if result:
        st.subheader("Tóm tắt các phương án")
        st.dataframe(scenario_table(result), hide_index=True, use_container_width=True)


if __name__ == "__main__":
    st.navigation([
        st.Page(main, title="Trang chủ", default=True),
        st.Page("pages/1_Control_Tower.py", title="Tổng quan vận hành"),
        st.Page("pages/2_Bottleneck_Cause.py", title="Điểm nghẽn và nguyên nhân"),
        st.Page("pages/3_Scenario_Comparison.py", title="So sánh phương án"),
        st.Page("pages/4_Recommendation.py", title="Đề xuất hành động"),
    ], expanded=True).run()
