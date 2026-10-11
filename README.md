# D2 Logistics Decision Twin

Prototype hỗ trợ operator dự báo bottleneck logistics và so sánh phương án can thiệp.
Phạm vi MVP: LINE_A, MAT_A/MAT_B, tuyến R1 và pool R2, 5 AMR,
forecast 60 phút theo khoảng 15 phút. Operator là người quyết định cuối cùng.

## Trạng thái triển khai

Forecast, future logistics state, bottleneck/cause diagnosis, SimPy what-if,
evaluation và dashboard đã được kết nối thành pipeline thật. Bộ test có cả
integration test dùng test doubles và acceptance test chạy toàn bộ module thật.
Không có dữ liệu KPI hay recommendation giả thay thế khi chạy app.

## Setup

Chạy từ thư mục gốc với Python 3.11+ (khuyến nghị Python 3.11):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Đặt gói CSV PEAK v2 trong `data/`, giữ cấu trúc:

```text
data/master/         material_master.csv, route_master.csv, resource_master.csv
data/history/        dữ liệu lịch sử
data/current/        current_state.csv
data/known_future/   known_future_events.csv, future_production_plan_15min.csv
data/model_ready/    model_training_15min.csv
data/validation_only/ chỉ dùng đánh giá sau khi đã tạo prediction
```

Dữ liệu là **synthetic**, phục vụ prototype, chưa chứng minh hiệu quả vận hành thực tế.
Không dùng `validation_only/` để train, forecast hoặc ra quyết định runtime.
Config loader từ chối runtime path nằm ngoài repo hoặc trỏ vào `validation_only/`.

## Train, test, dashboard

Chạy theo thứ tự:

```powershell
python scripts/train_forecast.py
python -m pytest -q
python -m streamlit run app/Home.py
```

Lệnh train tạo `artifacts/models/forecast_models.joblib` và in MAE, WAPE,
Pinball Loss, Quantile Coverage trên phần holdout theo thời gian. Nếu chưa có
model artifact, forecast service dùng baseline từ history.

Kiểm thử riêng phần tích hợp:

```powershell
python -m pytest tests/test_pipeline.py -q
```

`tests/test_pipeline.py` dùng test doubles cho Dương/Hà/Phú và chạy engine Quân thật. Chúng xác minh
thứ tự ghép nối, Normal không chạy SimPy, Demand Spike, AMR Failure có Reassign,
Multi-cause có combined scenarios, secondary bottleneck bị loại, seed/maintenance,
schema lỗi, audit CSV, lưu artifacts và không đọc validation labels.
`tests/test_real_pipeline.py` chạy forecast, future state, detection, diagnosis,
SimPy, evaluation, robustness và recommendation thật trên snapshot mặc định;
đồng thời bấm nút Run qua Streamlit AppTest. Các module còn có unit tests riêng.

Trong app, chọn decision mode, snapshot time, seed và bấm **Run Decision Twin**.
Mặc định là replay snapshot `2026-10-08 14:00:00`, khớp current CSV và
production plan bắt đầu +15 phút. Không tự lấy giờ máy để dự báo trên snapshot cũ.
Muốn đổi snapshot time phải cập nhật current state và known-future input tương ứng.

## Chứng minh 5 ca demo

```powershell
python scripts/demo_cases.py
python -m pytest tests/test_demo_cases.py tests/test_real_pipeline.py -q
```

`config/demo_cases.yaml` khai báo các thay đổi **đầu vào synthetic**: ca Normal
không có maintenance và có thêm AMR cho R1; Demand Spike tăng nhu cầu dự báo bằng
hệ số stress 1.5; Multi-cause hạ buffer MAT_A; Secondary Bottleneck tăng tải
R2. AMR Failure dùng nguyên snapshot PEAK v2. Script chạy forecast model, future
state, diagnosis, SimPy và decision engine thật cho từng ca; không chứa KPI hay
phương án được gán sẵn. Các ca stress chỉ dùng để chứng minh hành vi prototype,
không phải dự báo vận hành của snapshot mặc định.

## Kiến trúc và interface tích hợp

```text
Current state + known events + plan
  → Dương: ForecastPoint[] (R1 P10/P50/P90)
  → Hà: FutureState[] (R1/R2) → BottleneckEvent[]
  → nếu không bottleneck: No intervention required (không simulation)
  → Hà: Cause[]
  → Quân: Scenario[] → static feasibility
  → Phú: SimulationResult cho S0 và tất cả scenario (Expected P50)
  → Quân: dynamic constraints → Pareto → decision mode ranking
  → Phú: top 3 intervention + S0 chạy Favorable P10 / Adverse P90
  → Quân: robustness → DecisionPackage
  → Hạ: dashboard + operator audit
```

Entry point: `src.orchestration.pipeline.run_pipeline(decision_mode="balanced", now=None, seed=42)`.
Trả `PipelineResult`: run ID, snapshot, current input, forecasts, future states,
bottlenecks, causes, scenarios, simulation outputs, rejection reasons, ranks,
robustness và decision package. Normal có `decision_package=None` và S0, không
tạo SimulationResult giả. Chưa có can thiệp an toàn thì giữ S0 và báo rõ.

Shared dataclasses trong `src/common/schemas.py` được giữ nguyên. Các interface
đang được pipeline sử dụng:

```python
# Dương — src/forecast/service.py
forecast_future_drivers(now, horizon_min=60, interval_min=15) -> list[ForecastPoint]

# Hà — src/logistics/future_state.py
build_future_states(current_state, forecasts, known_events, config) -> list[FutureState]
# Hà — src/bottleneck/detector.py
detect_bottlenecks(future_states, now=now, thresholds=config["thresholds"]) -> list[BottleneckEvent]
# Hà — src/bottleneck/cause_diagnosis.py
diagnose_bottlenecks(bottlenecks, future_states, current_state, forecasts,
                     known_events, config) -> list[Cause]

# Phú — src/simulation/simulator.py
run_simulation(current_state, future_condition, scenario, seed=42) -> SimulationResult
```

`current_state`, `known_events`, `production_plan` là pandas DataFrame đọc từ CSV.
`config` gồm `system`, `thresholds`, `actions`, `decision`, `paths` tuyệt đối,
`config_paths`, `root`, kèm `now`, `known_events`, `production_plan` ở context runtime.
`FutureState.location` là route ID `R1` hoặc `R2`, đủ cả 4 timestamps mỗi route.
Forecast phải đúng +15/+30/+45/+60, quantiles hữu hạn không âm và có thứ tự.

`future_condition` gửi Phú là dict:

```python
{
    "condition": "expected",       # favorable / adverse
    "quantile": "p50",             # p10 / p90
    "forecasts": list_of_forecast_points,
    "known_events": events_dataframe,
    "production_plan": plan_dataframe,
    "config": runtime_config,
    "additional_amr_unavailable": 0,
}
```

Phú chọn đúng quantile cho demand/process/travel; apply maintenance trực tiếp ở
mọi condition. Khi config bật, adverse giảm thêm AMR theo
`additional_amr_unavailable`, không để số AMR xuống dưới 0. S0 và các scenario
dùng cùng input condition/seed; mỗi lần gọi nhận bản sao input để tránh sửa lẫn.
Timing action nằm trong `Action.parameters`, không thêm field vào shared schema.
R2 chỉ là tuyến AUX/pool; không tự biến R2 thành alternate route đến LINE_A.

Quân được gọi bằng interface có sẵn: `generate_scenarios(...)`,
`check_static_feasibility(...)`, `apply_dynamic_constraints(...)`,
`filter_pareto_front(...)`, `rank_scenarios(...)`, `evaluate_robustness(...)`,
`build_decision_package(...)`. KPI comparison do recommendation builder thực hiện.
Dashboard có dropdown `balanced`, `service_priority`, `low_disruption`.
Robustness chưa chạy cho scenario ngoài top được ghi “Not tested”.
Dynamic constraints so late delivery và AMR utilization của phương án với S0:
phương án không bị loại chỉ vì tình trạng quá tải đã tồn tại ở S0, nhưng bị loại
nếu làm các chỉ số này xấu thêm vượt ngưỡng YAML. Secondary bottleneck, starvation,
unmet consumption và overflow vẫn được kiểm tra trực tiếp.

Snapshot mặc định có maintenance của AMR03. Với model đã train, pipeline phát hiện
bottleneck R1, chẩn đoán `AMR_AVAILABILITY_DROP`, mô phỏng S0/S1 và đề xuất S1
`REASSIGN_AMR`; KPI và robustness đến từ SimPy. Đây là dữ liệu synthetic, không
phải khuyến nghị vận hành thực tế.

## Dashboard và artifacts

- Home: điều khiển pipeline và trạng thái module.
- Control Tower: current snapshot, forecast, capacity, queue, waiting, buffer,
  AMR và risk của detected events. Không suy diễn risk score cho state thiếu score.
- Bottleneck & Cause: Where/When/Lead Time/Severity/Risk, triggered rules, evidence.
- Scenario Comparison: S0 đầu bảng, KPI, phương án bị loại, ranks, robustness.
- Recommendation: actions/parameters/start/duration, KPI S0 và phương án chọn,
  improvement, side effects, robustness, APPROVE/MODIFY/REJECT và RUN AGAIN.

App lưu mỗi run thành JSON trong `artifacts/recommendations/<run_id>.json`.
Operator decision append vào `artifacts/operator_decisions.csv` có thời gian
Asia/Ho_Chi_Minh, run ID, snapshot, mode, seed, scenario ID, decision, notes.
MODIFY bắt buộc ghi nội dung cần sửa; đây là yêu cầu của operator, không tự thay
action hay tự chạy mô phỏng sửa đổi. CSV audit không gửi lệnh đến AMR thật.
Các ô có tiền tố công thức được escape khi lưu để mở CSV an toàn.

Không hard-code recommendation/KPI, không LLM chọn phương án, không cloud,
database, FastAPI, DRL hoặc OR-Tools trong core MVP.
