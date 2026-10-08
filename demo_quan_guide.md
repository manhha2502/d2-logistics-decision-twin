# 📦 HƯỚNG DẪN TÍCH HỢP & KẾT NỐI MODULE CỦA QUÂN
> **Phần sở hữu (Quân):** `Action Library → Scenario Generator → Evaluation → Recommendation Builder`  
> **Nhánh Git:** `feature/quan-decision-engine`

---

## 🚀 1. Cách chạy kiểm thử & Demo độc lập (How to run)

Mọi thành viên trong team khi clone nhánh của Quân về đều có thể kiểm tra nhanh bằng 2 lệnh:

### 1.1. Chạy Unit Tests tự động (12/12 Tests PASSED ✅)
```bash
python -m pytest tests/test_actions.py tests/test_evaluation.py tests/test_recommendation.py -v
```
*(Kiểm tra toàn bộ logic sinh kịch bản, lọc khả thi, lọc động secondary bottleneck, lọc Pareto và xếp hạng decision modes).*

### 1.2. Chạy Demo giả lập Pipeline (Giao diện trực quan)
Để chạy thử bản demo giả lập và xem giao diện HTML, chuyển sang nhánh demo:
```bash
# Chuyển sang nhánh demo để lấy file chạy
git checkout feature/quan-demo

# Chạy demo (tự động mở giao diện HTML trên trình duyệt)
python demo_quan.py

# Xem xong có thể quay lại nhánh làm việc
git checkout feature/quan-decision-engine
```

---

## 🔌 2. Hướng dẫn kết nối cho từng thành viên (Integration Guide)

Hệ thống hoạt động theo chuỗi chuyền dữ liệu:
$$\text{Hà (Causes)} \longrightarrow \text{Quân (Scenarios)} \longrightarrow \text{Phú (SimPy Results)} \longrightarrow \text{Quân (Decision Package)} \longrightarrow \text{Hạ (Dashboard)}$$

---

### 👩‍💻 2.1. Dành cho HÀ (Module Bottleneck & Cause Diagnosis)
* **Vị trí của bạn:** Đầu vào cho Quân.
* **Nhiệm vụ của Hà:** Sau khi phát hiện tắc nghẽn và chẩn đoán xong, Hà trả ra danh sách nguyên nhân: `causes: list[Cause]`.
* **Cách gọi phần của Quân:**
```python
from src.actions.scenario_generator import generate_scenarios

# Truyền danh sách causes của Hà vào:
# Quân sẽ tự động lọc action phù hợp và sinh tối đa 8 kịch bản (S0 luôn là baseline)
scenarios = generate_scenarios(causes=causes, max_scenarios=8)
```
* **Output nhận lại:** `scenarios: list[Scenario]` (sẵn sàng chuyển tiếp cho Phú).

---

### 👨‍💻 2.2. Dành cho PHÚ (Module SimPy What-if Digital Twin)
* **Vị trí của bạn:** Nhận kịch bản từ Quân $\rightarrow$ chạy mô phỏng SimPy $\rightarrow$ trả kết quả về cho Quân.
* **Cấu trúc dữ liệu Phú nhận được từ Quân (`Scenario`):**
  * `scenario.scenario_id`: Tên kịch bản (`"S0"`, `"S1"`, `"S2"`,...). Trong đó **`S0` luôn là kịch bản cơ sở (No Action)**.
  * `scenario.actions`: Danh sách các `Action` cần thực hiện trong kịch bản đó.
  * Mỗi action có:
    * `action.action_type`: Tên loại hành động (`"PRIORITIZE_REQUEST"`, `"REASSIGN_AMR"`, `"ADJUST_REPLENISHMENT_TIME"`, `"CONSOLIDATE_DELIVERY"`).
    * `action.parameters`: **Dict chứa toàn bộ thông số thực thi** (Phú chỉ cần đọc dict này):
      * `count`: Số lượng xe AMR cần mượn (ví dụ: `1`).
      * `from_route`: Tuyến bị mượn xe (`"R2"`).
      * `to_route`: Tuyến nhận xe (`"R1"`).
      * `start_time`: Thời điểm bắt đầu can thiệp (ví dụ: `"NOW"`).
      * `duration_min`: Thời lượng can thiệp mô phỏng (ví dụ: `45` phút).
      * `shift_minutes`: Thời gian lùi/tiến cấp hàng (ví dụ: `-15` phút).
* **Nhiệm vụ của Phú trả về cho Quân:** Phú chạy xong mô phỏng thì đóng gói kết quả vào dict dạng:
```python
sim_results = {
    "S0": SimulationResult(...), # Kết quả mô phỏng của S0
    "S1": SimulationResult(...), # Kết quả mô phỏng của S1
    ...
}
```
> ⚠️ **Lưu ý quan trọng cho Phú:** Nếu kịch bản nào (ví dụ mượn xe từ R2 sang R1) làm cho tuyến R2 bị tắc nghẽn nghiêm trọng, Phú hãy set cờ `secondary_bottleneck=True` trong `SimulationResult` để bộ lọc động của Quân tự động loại bỏ phương án nguy hiểm này!



### 🎨 2.4. Dành cho HẠ (Module Pipeline Orchestration & Streamlit Dashboard)
* **Vị trí của bạn:** Người ghép nối toàn bộ hệ thống end-to-end trong `src/orchestration/pipeline.py` và hiển thị lên giao diện Streamlit.
* **Cách Hạ gọi trọn gói phần của Quân:**

```python
from src.actions.scenario_generator import generate_scenarios
from src.recommendation.builder import build_decision_package

# --- BƯỚC 1: Sinh kịch bản từ nguyên nhân của Hà ---
scenarios = generate_scenarios(causes=causes, max_scenarios=8)

# --- BƯỚC 2: Phú chạy mô phỏng SimPy cho các kịch bản trên ---
sim_results = run_simulation_all(scenarios)

# --- BƯỚC 3: Quân đánh giá, lọc Pareto và chốt gói đề xuất tối ưu ---
decision_pkg = build_decision_package(
    bottleneck=bottleneck,
    causes=causes,
    scenarios=scenarios,
    sim_results=sim_results,
    decision_mode="balanced",  # Hoặc "service_priority", "low_disruption" từ dropdown của Hạ
    sim_results_by_condition=sim_by_condition, # Nếu có chạy thêm P10/P90
)

# --- BƯỚC 4: Hạ lấy dữ liệu từ `decision_pkg` hiển thị lên Dashboard ---
# Trang 3_Scenario_Comparison.py:
# - Hiển thị bảng so sánh KPI giữa S0 và các scenario trong `scenarios`

# Trang 4_Recommendation.py:
# - Kịch bản tối ưu nhất: decision_pkg.recommended_scenario.scenario_id (ví dụ: S4)
# - Các hành động cần làm : decision_pkg.recommended_scenario.actions
# - % Cải thiện so với S0 : decision_pkg.kpi_improvement["waiting_time_pct"], ...
# - Cảnh báo tác dụng phụ : decision_pkg.side_effects["warnings"]
# - Đánh giá độ bền       : decision_pkg.robustness
```

---

## ⚙️ 3. Tùy chỉnh tham số & Trọng số (Config YAML)
Nếu team cần tinh chỉnh luật hoặc trọng số, chỉ cần sửa 2 file YAML (không cần sửa code):
* [config/actions.yaml](file:///c:/10000hcode%29%29%29%29%29/DENSO/config/actions.yaml): Thêm/sửa tham số mặc định của Action, mức độ xáo trộn (`disruption_level`), xung đột giữa các hành động.
* [config/decision_modes.yaml](file:///c:/10000hcode%29%29%29%29%29/DENSO/config/decision_modes.yaml): Tinh chỉnh trọng số chấm điểm của 3 chế độ (`balanced`, `service_priority`, `low_disruption`) và ngưỡng lọc ràng buộc động (`max_buffer_overflow`, `max_late_delivery_count`...).

---

> 💖 *Ai có đọc, và đọc đến tận đây thì người đó rất xênh géi / đẹp trai (check coi team có đọc kỹ không nha :v)*