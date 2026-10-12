"""Vietnamese labels and operator-facing explanations for pipeline results.

Only presentation text lives here; scenario IDs, action codes and model outputs
stay unchanged so the dashboard cannot alter a decision.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


FIELDS = {
    "timestamp": "Thời điểm", "location": "Tuyến", "entity_type": "Loại",
    "entity_id": "Mã", "available": "Sẵn sàng", "battery_pct": "Pin (%)",
    "current_level_totes": "Tồn buffer (tote)", "dcr": "Nhu cầu / năng lực",
    "fill_ratio": "Mức đầy buffer", "queue_end_totes": "Hàng đợi (tote)",
    "route_id": "Tuyến", "status": "Trạng thái", "utilization": "Mức sử dụng",
    "demand": "Nhu cầu (tote / 15 phút)", "capacity": "Năng lực (tote / 15 phút)",
    "throughput": "Số tote xử lý", "queue_start": "Hàng đợi đầu kỳ (tote)",
    "queue_end": "Hàng đợi cuối kỳ (tote)", "waiting_time": "Thời gian chờ (phút)",
    "buffer_mat_a": "Buffer MAT_A (tote)", "buffer_mat_b": "Buffer MAT_B (tote)",
    "unmet_consumption": "Nhu cầu vật tư chưa đáp ứng (tote)",
    "overflow": "Lượng tràn (tote)", "amr_available": "AMR sẵn sàng",
    "travel_loaded": "Di chuyển có tải (phút)",
    "travel_empty": "Di chuyển không tải (phút)",
    "picking_time": "Lấy hàng (phút)", "loading_time": "Bốc hàng (phút)",
    "unloading_time": "Dỡ hàng (phút)", "baseline": "Mức gốc",
    "forecast": "Mức dự báo", "increase_pct": "Mức tăng (%)",
    "decrease_pct": "Mức giảm (%)", "resource_id": "AMR",
    "event_type": "Sự kiện", "buffer_ratios": "Mức đầy buffer",
    "threshold": "Ngưỡng", "queue_overflow": "Hàng đợi tràn (tote)",
    "buffer_overflow": "Buffer tràn (tote)", "predicted_time": "Thời điểm dự báo",
    "avg_waiting_time": "Chờ trung bình (phút)",
    "max_waiting_time": "Chờ lâu nhất (phút)",
    "avg_queue": "Hàng đợi trung bình (tote)",
    "max_queue": "Hàng đợi lớn nhất (tote)",
    "late_delivery_count": "Lượt giao trễ", "service_level": "Mức đáp ứng (%)",
    "starvation_minutes": "Thiếu vật tư (phút)",
    "secondary_bottleneck": "Nghẽn phụ ở R2",
}

CAUSES = {
    "DEMAND_SPIKE": "Nhu cầu tăng đột biến",
    "AMR_AVAILABILITY_DROP": "Số AMR sẵn sàng giảm",
    "TRAVEL_TIME_INCREASE": "Thời gian di chuyển tăng",
    "PICKING_SLOWDOWN": "Khâu lấy hàng chậm",
    "HANDLING_TIME_INCREASE": "Thời gian bốc dỡ tăng",
    "BUFFER_LOW": "Buffer sắp cạn",
    "BUFFER_FULL": "Buffer gần đầy",
}

RULES = {
    "DCR_CRITICAL": "Nhu cầu vượt xa năng lực",
    "DCR_HIGH": "Nhu cầu vượt năng lực",
    "QUEUE_GROWTH": "Hàng đợi tăng",
    "HIGH_UTILIZATION": "Tuyến sử dụng gần hết năng lực",
    "CRITICAL_LOW_BUFFER": "Buffer ở mức cạn nghiêm trọng",
    "LOW_BUFFER": "Buffer ở mức thấp",
    "BUFFER_OVERFLOW": "Buffer bị tràn",
    "UNMET_CONSUMPTION": "Nhu cầu vật tư chưa được đáp ứng",
}

REJECTIONS = {
    "BUFFER_OVERFLOW": "Gây tràn buffer",
    "STARVATION_DETECTED": "Gây thiếu vật tư",
    "UNMET_CONSUMPTION": "Không đáp ứng đủ vật tư",
    "CRITICAL_SECONDARY_BOTTLENECK": "Gây nghẽn phụ nghiêm trọng ở R2",
    "SEVERE_LATE_DELIVERY": "Số lượt giao trễ tăng quá ngưỡng",
    "UNACCEPTABLE_RESOURCE_OVERLOAD": "AMR bị quá tải",
    "MISSING_SIMULATION_RESULT": "Thiếu kết quả mô phỏng",
}

IMPROVEMENTS = {
    "waiting_time_pct": "Giảm thời gian chờ",
    "queue_reduction_pct": "Giảm hàng đợi",
    "late_delivery_reduction_pct": "Giảm lượt giao trễ",
    "starvation_reduction_pct": "Giảm thời gian thiếu vật tư",
    "unmet_consumption_reduction_pct": "Giảm nhu cầu vật tư chưa đáp ứng",
    "throughput_pct": "Tăng số tote xử lý",
    "service_level_pct": "Tăng mức đáp ứng",
    "disruption": "Mức xáo trộn vận hành",
}

MODE_NAMES = {"balanced": "Cân bằng tổng thể", "service_priority": "Ưu tiên mức đáp ứng",
              "low_disruption": "Hạn chế xáo trộn"}
CONDITIONS = {"favorable": "Thuận lợi (P10)", "expected": "Kỳ vọng (P50)",
              "adverse": "Bất lợi (P90)"}
RATINGS = {"ROBUST": "Ổn định", "MODERATE": "Cần theo dõi",
           "SENSITIVE": "Nhạy với biến động", "UNTESTED_MULTI_CONDITION": "Chưa kiểm tra đủ"}
SEVERITIES = {"Critical": "Nghiêm trọng", "High": "Cao", "Medium": "Trung bình",
              "CRITICAL": "Nghiêm trọng", "HIGH": "Cao", "MEDIUM": "Trung bình"}
def time_text(value: Any) -> str:
    """Show complete local snapshot time without a clipped ISO timestamp."""
    return pd.Timestamp(value).strftime("%d/%m/%Y %H:%M")


def number_text(value: Any) -> str:
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, (int, float)):
        if isinstance(value, int):
            return str(value)
        return f"{value:,.2f}".rstrip("0").rstrip(".") or "0"
    if isinstance(value, (datetime, pd.Timestamp)):
        return time_text(value)
    if value is None:
        return "—"
    if isinstance(value, dict):
        return ", ".join(f"{key}: {number_text(item)}" for key, item in value.items()) or "—"
    if isinstance(value, list):
        return ", ".join(map(number_text, value)) or "—"
    if pd.isna(value):
        return "—"
    return str(value)


def evidence_table(evidence: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([{"Chỉ số": FIELDS.get(key, key), "Giá trị": number_text(value)}
                         for key, value in evidence.items()])


def rejection_text(reason: str) -> str:
    code, _, detail = reason.partition(":")
    return REJECTIONS.get(code, code) + (f": {detail.strip()}" if detail else "")


def action_text(action: Any) -> str:
    """Turn an action code and actual parameters into an operator instruction."""
    p = action.parameters
    kind = action.action_type
    if kind == "REASSIGN_AMR":
        return f"Điều chuyển {p.get('count', 1)} AMR từ {p.get('from_route', '?')} sang {p.get('to_route', '?')}"
    if kind == "PRIORITIZE_REQUEST":
        material = p.get("material_id", "ALL")
        target = "mọi vật tư" if material == "ALL" else f"vật tư {material}"
        return f"Ưu tiên yêu cầu cấp {target} cho {p.get('target_line', '?')}"
    if kind == "ALTERNATE_ROUTE":
        return f"Chuyển {p.get('target_route', '?')} sang tuyến thay thế {p.get('alternate_route_id') or 'cần xác nhận'}"
    if kind == "ADJUST_REPLENISHMENT_TIME":
        shift = int(p.get("shift_minutes", 0))
        direction = "sớm hơn" if shift < 0 else "muộn hơn"
        return f"Điều chỉnh cấp vật tư cho {p.get('target_line', '?')} {direction} {abs(shift)} phút"
    if kind == "CONSOLIDATE_DELIVERY":
        return f"Gộp chuyến giao trên {p.get('target_route', '?')}, mỗi chuyến {p.get('batch_size_totes', '?')} tote"
    return kind


def action_timing(action: Any) -> str:
    start = action.parameters.get("start_time", "NOW")
    when = "Thực hiện ngay" if start == "NOW" else f"Bắt đầu lúc {number_text(start)}"
    return f"{when}; duy trì {action.parameters.get('duration_min', 45)} phút"
