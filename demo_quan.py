import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

# Thêm thư mục gốc vào path để import các module của dự án
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Cấu hình UTF-8 cho stdout trên Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.common.schemas import (
    BottleneckEvent,
    Cause,
    DecisionPackage,
    Scenario,
    SimulationResult,
)
from src.actions.library import get_candidate_actions, load_action_config
from src.actions.scenario_generator import generate_scenarios
from src.actions.feasibility import check_static_feasibility
from src.evaluation.constraints import apply_dynamic_constraints
from src.evaluation.kpi_compare import compare_kpi_vs_baseline
from src.evaluation.pareto import filter_pareto_front
from src.evaluation.robustness import rank_scenarios, evaluate_robustness
from src.recommendation.builder import build_decision_package


def run_pipeline_demo():
    print("=" * 80)
    print("🚀 D2 LOGISTICS DECISION TWIN — DEMO PIPELINE (PHẦN QUÂN)")
    print("=" * 80)

    # 1. KHỞI TẠO DỮ LIỆU ĐẦU VÀO TỪ HÀ (BOTTLENECK & CAUSES)
    bottleneck = BottleneckEvent(
        location="R1 (Warehouse -> LINE_A)",
        predicted_time=datetime.now(),
        lead_time_min=30,
        severity="HIGH",
        risk_score=84.2,
        triggered_rules=["DCR_HIGH", "QUEUE_GROWTH", "LOW_BUFFER"],
        evidence={"dcr": 1.28, "queue_totes": 8.5, "buffer_mat_a": 12.0},
    )

    causes = [
        Cause(
            cause_type="DEMAND_SPIKE",
            contribution="high",
            evidence={"forecast_increase_pct": 35.0, "reason": "Kế hoạch sản xuất LINE_A tăng đột biến"},
        ),
        Cause(
            cause_type="AMR_AVAILABILITY_DROP",
            contribution="medium",
            evidence={"available_amr": 2, "normal_amr": 3, "reason": "AMR03 bảo trì định kỳ"},
        ),
        Cause(
            cause_type="BUFFER_LOW",
            contribution="medium",
            evidence={"material_id": "MAT_A", "fill_ratio": 0.42, "reason": "Buffer đang chạm reorder point"},
        ),
    ]

    print("\n[BƯỚC 1] NHẬN NGUYÊN NHÂN TỪ HÀ:")
    print(f"  • Vị trí nghẽn : {bottleneck.location}")
    print(f"  • Mức độ       : {bottleneck.severity} (Risk score: {bottleneck.risk_score}/100)")
    for i, c in enumerate(causes, 1):
        print(f"  • Nguyên nhân {i}: {c.cause_type} ({c.contribution}) -> {c.evidence}")

    # 2. SINH KỊCH BẢN (SCENARIO GENERATION & STATIC FEASIBILITY)
    scenarios = generate_scenarios(causes, max_scenarios=8)
    print(f"\n[BƯỚC 2] TỰ ĐỘNG SINH KỊCH BẢN & LỌC TĨNH:")
    print(f"  Đã tạo {len(scenarios)} kịch bản khả thi (S0 là baseline):")
    for sc in scenarios:
        act_names = [a.action_type for a in sc.actions] if sc.actions else ["NO_ACTION (Giữ nguyên)"]
        print(f"  • [{sc.scenario_id}] Actions: {', '.join(act_names)} | Độ xáo trộn: {sc.estimated_disruption:.1f} | Phủ: {sc.cause_coverage}")

    # 3. GIẢ LẬP KẾT QUẢ MÔ PHỎNG SIMPY TỪ PHÚ
    sim_results: dict[str, SimulationResult] = {}
    
    # Baseline S0
    sim_results["S0"] = SimulationResult(
        scenario_id="S0",
        avg_waiting_time=9.5,
        max_waiting_time=15.0,
        avg_queue=6.8,
        max_queue=11.0,
        late_delivery_count=4,
        throughput=92.0,
        service_level=81.5,
        starvation_minutes=0.0,
        unmet_consumption=0.0,
        buffer_overflow=0.0,
        amr_utilization={"AMR01": 0.95, "AMR02": 0.94},
        secondary_bottleneck=False,
    )

    # Mock kết quả cho các kịch bản
    # Giả lập S1..S6 với các mức cải thiện khác nhau
    metrics_presets = [
        {"wait": 5.2, "queue": 3.6, "late": 1, "tp": 108.0, "sl": 93.5, "sec": False},
        {"wait": 3.8, "queue": 2.2, "late": 0, "tp": 118.0, "sl": 96.8, "sec": False},
        {"wait": 6.8, "queue": 4.5, "late": 2, "tp": 102.0, "sl": 88.0, "sec": False},
        {"wait": 2.4, "queue": 1.2, "late": 0, "tp": 126.0, "sl": 99.1, "sec": False},
        {"wait": 4.2, "queue": 2.9, "late": 1, "tp": 112.0, "sl": 95.2, "sec": False},
        {"wait": 3.1, "queue": 1.9, "late": 0, "tp": 121.0, "sl": 97.4, "sec": False},
        # Một kịch bản nguy hiểm gây nghẽn phụ để test Dynamic Constraint
        {"wait": 2.1, "queue": 1.0, "late": 0, "tp": 128.0, "sl": 99.5, "sec": True},
    ]

    for idx, sc in enumerate(scenarios[1:], start=0):
        m = metrics_presets[min(idx, len(metrics_presets) - 1)]
        sim_results[sc.scenario_id] = SimulationResult(
            scenario_id=sc.scenario_id,
            avg_waiting_time=m["wait"],
            max_waiting_time=m["wait"] * 1.4,
            avg_queue=m["queue"],
            max_queue=m["queue"] * 1.5,
            late_delivery_count=m["late"],
            throughput=m["tp"],
            service_level=m["sl"],
            starvation_minutes=0.0,
            unmet_consumption=0.0,
            buffer_overflow=0.0,
            amr_utilization={"AMR01": 0.82, "AMR02": 0.80},
            secondary_bottleneck=m["sec"],
        )

    print("\n[BƯỚC 3] KẾT QUẢ MÔ PHỎNG SIMPY TƯƠNG ỨNG:")
    print(f"  {'Scenario':<10} | {'Wait (min)':<11} | {'Queue (totes)':<14} | {'Late':<6} | {'Throughput':<11} | {'Service Level':<14} | {'Sec. Bottleneck'}")
    print("  " + "-" * 90)
    for sc in scenarios:
        r = sim_results[sc.scenario_id]
        sec_str = "CẢNH BÁO: CÓ!" if r.secondary_bottleneck else "Không"
        print(f"  {sc.scenario_id:<10} | {r.avg_waiting_time:<11.1f} | {r.avg_queue:<14.1f} | {r.late_delivery_count:<6} | {r.throughput:<11.1f} | {r.service_level:<13.1f}% | {sec_str}")

    # 4. LỌC RÀNG BUỘC ĐỘNG (DYNAMIC CONSTRAINTS)
    valid_scs, rejected = apply_dynamic_constraints(scenarios, sim_results)
    print("\n[BƯỚC 4] LỌC DYNAMIC CONSTRAINTS:")
    print(f"  • Kịch bản hợp lệ: {[s.scenario_id for s in valid_scs]}")
    if rejected:
        for sid, reas in rejected.items():
            print(f"  • Đã loại [{sid}]: {', '.join(reas)}")
    else:
        print("  • Không có kịch bản nào bị loại bởi Dynamic Constraints.")

    # 5. LỌC TẬP TỐI ƯU PARETO
    pareto_scs = filter_pareto_front(valid_scs, sim_results)
    print("\n[BƯỚC 5] LỌC TẬP PARETO (NON-DOMINATED SORTING):")
    print(f"  • Tập Pareto tối ưu: {[s.scenario_id for s in pareto_scs]}")

    # 6. XẾP HẠNG THEO 3 DECISION MODES
    print("\n[BƯỚC 6] XẾP HẠNG THEO TỪNG CHẾ ĐỘ RA QUYẾT ĐỊNH (DECISION MODES):")
    modes = ["balanced", "service_priority", "low_disruption"]
    rankings_by_mode = {}
    for m in modes:
        ranked = rank_scenarios(pareto_scs, sim_results, decision_mode=m)
        rankings_by_mode[m] = ranked
        print(f"\n  ► Chế độ: {m.upper()}")
        for rank_idx, (sc, score) in enumerate(ranked, 1):
            act_names = [a.action_type for a in sc.actions] if sc.actions else ["NO_ACTION"]
            print(f"     Top {rank_idx}: [{sc.scenario_id}] Điểm: {score:.3f} | Actions: {', '.join(act_names)}")

    # 7. ROBUSTNESS MULTI-CONDITION
    sim_by_condition = {
        "expected": sim_results,
        "favorable": {
            sid: SimulationResult(
                scenario_id=sid,
                avg_waiting_time=max(0.5, res.avg_waiting_time * 0.7),
                max_waiting_time=res.max_waiting_time * 0.7,
                avg_queue=max(0.5, res.avg_queue * 0.6),
                max_queue=res.max_queue * 0.6,
                late_delivery_count=0,
                throughput=res.throughput * 1.1,
                service_level=min(100.0, res.service_level + 3.0),
                starvation_minutes=0.0,
                unmet_consumption=0.0,
                buffer_overflow=0.0,
                amr_utilization=res.amr_utilization,
                secondary_bottleneck=False,
            )
            for sid, res in sim_results.items()
        },
        "adverse": {
            sid: SimulationResult(
                scenario_id=sid,
                avg_waiting_time=res.avg_waiting_time * 1.3,
                max_waiting_time=res.max_waiting_time * 1.3,
                avg_queue=res.avg_queue * 1.4,
                max_queue=res.max_queue * 1.4,
                late_delivery_count=res.late_delivery_count + 1,
                throughput=res.throughput * 0.9,
                service_level=max(70.0, res.service_level - 5.0),
                starvation_minutes=0.0,
                unmet_consumption=0.0,
                buffer_overflow=0.0,
                amr_utilization=res.amr_utilization,
                secondary_bottleneck=False,
            )
            for sid, res in sim_results.items()
        },
    }

    # 8. ĐÓNG GÓI RECOMMENDATION CHO CHẾ ĐỘ BALANCED
    decision_pkg = build_decision_package(
        bottleneck=bottleneck,
        causes=causes,
        scenarios=pareto_scs,
        sim_results=sim_results,
        decision_mode="balanced",
        sim_results_by_condition=sim_by_condition,
    )

    rec_sc = decision_pkg.recommended_scenario
    rec_res = decision_pkg.recommended_result
    base_res = decision_pkg.baseline_result

    print("\n" + "=" * 80)
    print("🏆 GÓI QUYẾT ĐỊNH ĐỀ XUẤT CUỐI CÙNG (DECISION PACKAGE)")
    print("=" * 80)
    print(f"• KỊCH BẢN ĐỀ XUẤT     : {rec_sc.scenario_id}")
    print(f"• CÁC HÀNH ĐỘNG        : {[a.action_type for a in rec_sc.actions]}")
    for a in rec_sc.actions:
        print(f"   -> Tham số {a.action_type}: {a.parameters}")
    print(f"\n• SO SÁNH VỚI BASELINE (S0):")
    print(f"   - Thời gian chờ (Waiting) : {base_res.avg_waiting_time:.1f} min  -> {rec_res.avg_waiting_time:.1f} min  (Cải thiện {decision_pkg.kpi_improvement['waiting_time_pct']:.1f}%)")
    print(f"   - Hàng đợi (Queue)        : {base_res.avg_queue:.1f} totes -> {rec_res.avg_queue:.1f} totes (Cải thiện {decision_pkg.kpi_improvement['queue_reduction_pct']:.1f}%)")
    print(f"   - Giao hàng trễ (Late)    : {base_res.late_delivery_count} đơn     -> {rec_res.late_delivery_count} đơn     (Cải thiện {decision_pkg.kpi_improvement['late_delivery_reduction_pct']:.1f}%)")
    print(f"   - Thông lượng (Throughput): {base_res.throughput:.1f} t/h   -> {rec_res.throughput:.1f} t/h   (Tăng {decision_pkg.kpi_improvement['throughput_pct']:.1f}%)")
    print(f"   - Mức dịch vụ (Service)   : {base_res.service_level:.1f}%    -> {rec_res.service_level:.1f}%    (Tăng {decision_pkg.kpi_improvement['service_level_pct']:.1f}%)")

    rob_info = decision_pkg.robustness.get(rec_sc.scenario_id, {})
    print(f"\n• ĐỘ BỀN (ROBUSTNESS)   : Đánh giá [{rob_info.get('rating', 'ROBUST')}] (Sụt giảm ở kịch bản xấu nhất: {rob_info.get('adverse_drop_pct', 0.0):.1f}%)")
    if decision_pkg.side_effects.get("warnings"):
        print(f"• CẢNH BÁO TÁC DỤNG PHỤ  : {'; '.join(decision_pkg.side_effects['warnings'])}")

    # 9. TẠO GIAO DIỆN WEB HTML ĐƠN GIẢN
    html_content = generate_html_dashboard(
        bottleneck, causes, scenarios, sim_results, rankings_by_mode, decision_pkg
    )
    html_file = Path("demo_quan_dashboard.html")
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print("\n" + "=" * 80)
    print(f"✨ Giao diện web trực quan đã được tạo tại file: {html_file.resolve()}")
    print("✨ (File này đã được cấu hình loại trừ trong Git, an toàn 100%)")
    print("=" * 80)

    # Tự động mở trình duyệt
    try:
        webbrowser.open(html_file.resolve().as_uri())
        print("🌐 Đã mở giao diện Dashboard trên trình duyệt!")
    except Exception:
        pass


def generate_html_dashboard(bottleneck, causes, scenarios, sim_results, rankings_by_mode, decision_pkg):
    rec_sc = decision_pkg.recommended_scenario
    rec_res = decision_pkg.recommended_result
    base_res = decision_pkg.baseline_result
    kpi_imp = decision_pkg.kpi_improvement

    # HTML rows for scenarios
    table_rows = ""
    for sc in scenarios:
        r = sim_results.get(sc.scenario_id)
        if not r:
            continue
        is_rec = sc.scenario_id == rec_sc.scenario_id
        is_base = sc.scenario_id == "S0"
        badge = ""
        row_class = ""
        if is_rec:
            badge = '<span class="badge badge-success">★ ĐƯỢC CHỌN</span>'
            row_class = "row-recommended"
        elif is_base:
            badge = '<span class="badge badge-secondary">BASELINE</span>'
            row_class = "row-baseline"

        act_text = ", ".join([a.action_type for a in sc.actions]) if sc.actions else "No Action"
        sec_text = '<span class="text-danger font-bold">CÓ NGHẼN PHỤ!</span>' if r.secondary_bottleneck else "Không"

        table_rows += f"""
        <tr class="{row_class}">
            <td><strong>{sc.scenario_id}</strong> {badge}</td>
            <td><code>{act_text}</code></td>
            <td>{r.avg_waiting_time:.1f} m</td>
            <td>{r.avg_queue:.1f}</td>
            <td>{r.late_delivery_count}</td>
            <td>{r.throughput:.1f}</td>
            <td><strong>{r.service_level:.1f}%</strong></td>
            <td>{sc.estimated_disruption:.1f}</td>
            <td>{sec_text}</td>
        </tr>
        """

    # Rankings HTML
    rankings_html = ""
    for mode, ranked in rankings_by_mode.items():
        mode_titles = {
            "balanced": "⚖️ Chế độ Cân Bằng (Balanced)",
            "service_priority": "🚀 Ưu Tiên Dịch Vụ (Service Priority)",
            "low_disruption": "🛡️ Hạn Chế Xáo Trộn (Low Disruption)",
        }
        rankings_html += f"""
        <div class="card ranking-card">
            <h4>{mode_titles.get(mode, mode.upper())}</h4>
            <div class="ranking-list">
        """
        for idx, (sc, score) in enumerate(ranked, 1):
            act_names = ", ".join([a.action_type for a in sc.actions]) if sc.actions else "No Action"
            bar_width = int(score * 100)
            is_top = idx == 1
            rankings_html += f"""
            <div class="ranking-item {'top-rank' if is_top else ''}">
                <div class="rank-num">#{idx}</div>
                <div class="rank-info">
                    <div class="rank-title"><strong>{sc.scenario_id}</strong>: {act_names}</div>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" style="width: {bar_width}%;"></div>
                    </div>
                </div>
                <div class="rank-score">{(score*100):.1f} pts</div>
            </div>
            """
        rankings_html += "</div></div>"

    # Action params HTML
    action_details = ""
    for a in rec_sc.actions:
        action_details += f"""
        <div class="action-box">
            <h5>⚡ {a.action_type} (ID: {a.action_id})</h5>
            <ul>
        """
        for k, v in a.parameters.items():
            action_details += f"<li><strong>{k}:</strong> {v}</li>"
        action_details += "</ul></div>"

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>D2 Logistics Decision Twin — Demo Dashboard (Quân)</title>
    <style>
        :root {{
            --bg-color: #0f172a;
            --surface-color: #1e293b;
            --card-border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-blue: #38bdf8;
            --accent-green: #22c55e;
            --accent-amber: #f59e0b;
            --accent-red: #ef4444;
            --font-stack: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: var(--font-stack);
            line-height: 1.5;
            padding: 24px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .header h1 {{ font-size: 24px; color: var(--accent-blue); }}
        .badge {{
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: bold;
            display: inline-block;
        }}
        .badge-danger {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }}
        .badge-success {{ background: rgba(34, 197, 94, 0.2); color: var(--accent-green); border: 1px solid var(--accent-green); }}
        .badge-secondary {{ background: rgba(148, 163, 184, 0.2); color: var(--text-muted); border: 1px solid var(--card-border); }}
        
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
        .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
        
        .card {{
            background: var(--surface-color);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 20px;
        }}
        .card h3, .card h4 {{ margin-bottom: 12px; color: var(--text-main); }}
        
        /* Recommendation Hero Card */
        .hero-card {{
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.9), rgba(15, 23, 42, 0.95));
            border: 2px solid var(--accent-green);
            box-shadow: 0 0 25px rgba(34, 197, 94, 0.15);
        }}
        .kpi-metric-grid {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin: 16px 0;
        }}
        .kpi-box {{
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--card-border);
            padding: 12px;
            border-radius: 8px;
            text-align: center;
        }}
        .kpi-title {{ font-size: 12px; color: var(--text-muted); text-transform: uppercase; }}
        .kpi-val {{ font-size: 20px; font-weight: bold; margin: 4px 0; color: var(--accent-blue); }}
        .kpi-change {{ font-size: 13px; font-weight: bold; color: var(--accent-green); }}
        
        /* Tables */
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        th, td {{
            padding: 12px 14px;
            text-align: left;
            border-bottom: 1px solid var(--card-border);
        }}
        th {{ background: rgba(15, 23, 42, 0.6); color: var(--text-muted); }}
        .row-recommended {{ background: rgba(34, 197, 94, 0.08); font-weight: 500; }}
        .row-baseline {{ background: rgba(148, 163, 184, 0.04); }}
        code {{ background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; font-size: 12px; color: var(--accent-amber); }}
        
        /* Action Box */
        .action-box {{
            background: rgba(15, 23, 42, 0.7);
            border-left: 3px solid var(--accent-blue);
            padding: 10px 14px;
            margin-top: 10px;
            border-radius: 0 6px 6px 0;
        }}
        .action-box ul {{ padding-left: 20px; margin-top: 6px; font-size: 13px; color: var(--text-muted); }}
        
        /* Rankings */
        .ranking-item {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .rank-num {{
            font-size: 16px;
            font-weight: bold;
            color: var(--text-muted);
            width: 30px;
        }}
        .top-rank .rank-num {{ color: var(--accent-green); }}
        .rank-info {{ flex: 1; }}
        .rank-title {{ font-size: 13px; margin-bottom: 4px; }}
        .progress-bar-bg {{
            height: 6px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 3px;
            overflow: hidden;
        }}
        .progress-bar-fill {{
            height: 100%;
            background: var(--accent-blue);
            border-radius: 3px;
        }}
        .top-rank .progress-bar-fill {{ background: var(--accent-green); }}
        .rank-score {{ font-size: 13px; font-weight: bold; color: var(--text-muted); }}
        
        .warning-banner {{
            background: rgba(245, 158, 11, 0.15);
            border: 1px solid var(--accent-amber);
            color: var(--accent-amber);
            padding: 12px 16px;
            border-radius: 8px;
            margin-top: 16px;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>🧠 D2 Logistics Decision Twin — Decision Engine</h1>
            <p style="color: var(--text-muted); font-size: 14px;">Module: Action Library → Scenario Generator → Evaluation → Recommendation (Phần Quân)</p>
        </div>
        <div>
            <span class="badge badge-danger">SỰ CỐ PHÁT HIỆN: HIGH RISK</span>
        </div>
    </div>

    <!-- Bottleneck Context & Recommendation Hero -->
    <div class="grid-2">
        <div class="card">
            <h3>⚠️ Thông tin tắc nghẽn (Input từ Hà)</h3>
            <p><strong>Vị trí:</strong> {bottleneck.location}</p>
            <p><strong>Thời gian dự kiến:</strong> +{bottleneck.lead_time_min} phút nữa | <strong>Risk Score:</strong> {bottleneck.risk_score}/100</p>
            <div style="margin-top: 12px;">
                <strong>Nguyên nhân gốc rễ (Root Causes):</strong>
                <ul style="padding-left: 20px; margin-top: 6px; font-size: 14px;">
                    {"".join([f"<li><b>{c.cause_type}</b> ({c.contribution}) — {c.evidence.get('reason', '')}</li>" for c in causes])}
                </ul>
            </div>
        </div>

        <div class="card hero-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h3>🏆 Đề xuất phương án tối ưu (Decision Package)</h3>
                <span class="badge badge-success">KHUYÊN DÙNG: {rec_sc.scenario_id}</span>
            </div>
            
            <div class="kpi-metric-grid">
                <div class="kpi-box">
                    <div class="kpi-title">Thời gian chờ</div>
                    <div class="kpi-val">{rec_res.avg_waiting_time:.1f} m</div>
                    <div class="kpi-change">↓ {kpi_imp['waiting_time_pct']:.1f}%</div>
                </div>
                <div class="kpi-box">
                    <div class="kpi-title">Hàng đợi</div>
                    <div class="kpi-val">{rec_res.avg_queue:.1f}</div>
                    <div class="kpi-change">↓ {kpi_imp['queue_reduction_pct']:.1f}%</div>
                </div>
                <div class="kpi-box">
                    <div class="kpi-title">Đơn trễ</div>
                    <div class="kpi-val">{rec_res.late_delivery_count}</div>
                    <div class="kpi-change">↓ {kpi_imp['late_delivery_reduction_pct']:.0f}%</div>
                </div>
                <div class="kpi-box">
                    <div class="kpi-title">Thông lượng</div>
                    <div class="kpi-val">{rec_res.throughput:.0f}</div>
                    <div class="kpi-change">↑ {kpi_imp['throughput_pct']:.1f}%</div>
                </div>
                <div class="kpi-box">
                    <div class="kpi-title">Service Level</div>
                    <div class="kpi-val">{rec_res.service_level:.1f}%</div>
                    <div class="kpi-change">↑ {kpi_imp['service_level_pct']:.1f}%</div>
                </div>
            </div>

            <p style="font-size: 14px; margin-top: 10px;"><strong>Chi tiết hành động điều phối:</strong></p>
            {action_details}

            {"<div class='warning-banner'>⚠️ " + '; '.join(decision_pkg.side_effects['warnings']) + "</div>" if decision_pkg.side_effects.get("warnings") else ""}
        </div>
    </div>

    <!-- Scenarios Table -->
    <div class="card" style="margin-bottom: 24px;">
        <h3>📊 Danh sách kịch bản mô phỏng & Đánh giá (Scenarios Comparison)</h3>
        <table>
            <thead>
                <tr>
                    <th>Scenario ID</th>
                    <th>Hành động (Actions)</th>
                    <th>Chờ TB</th>
                    <th>Queue TB</th>
                    <th>Đơn trễ</th>
                    <th>Throughput</th>
                    <th>Service Level</th>
                    <th>Xáo trộn</th>
                    <th>Nghẽn phụ (R2)</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>

    <!-- 3 Decision Modes Ranking -->
    <h3>🎯 Bảng xếp hạng theo từng mục tiêu vận hành (Decision Modes)</h3>
    <div class="grid-3">
        {rankings_html}
    </div>

</body>
</html>
"""


if __name__ == "__main__":
    run_pipeline_demo()
