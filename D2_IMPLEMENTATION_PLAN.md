# D2 Logistics Decision Twin — Kế hoạch triển khai & phân công

> Mục tiêu: dùng tài liệu này để giao việc trực tiếp cho 5 thành viên hoặc đưa nguyên phần tương ứng cho AI Agent.

---

# 1. Phân công tổng

| Người     | Phần sở hữu                                             | Input chính                                         | Output bắt buộc                                 | Khi nào được coi là xong                                                                     |
| --------- | ------------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------- | -------------------------------------------------------------------------------------------- |
| **Hà**    | Logistics State → Bottleneck → Cause Diagnosis          | Master, current state, forecast, known events       | `FutureState[]`, `BottleneckEvent[]`, `Cause[]` | Forecast đi vào → trả được Where / When / Severity / Cause                                   |
| **Dương** | Data Pipeline + Forecast P10/P50/P90                    | Toàn bộ history + production plan                   | `ForecastPoint[]` + models + metrics            | Một command train được model và một function forecast +15/+30/+45/+60                        |
| **Phú**   | SimPy What-if Digital Twin                              | Master, current state, future condition, `Scenario` | `SimulationResult`                              | S0 và các scenario chạy cùng future condition, trả KPI + secondary bottleneck                |
| **Quân**  | Action Library → Scenario → Evaluation → Recommendation | Cause, current resources, simulation results        | `Scenario[]`, ranked results, `DecisionPackage` | Từ Cause → tự sinh scenario → loại infeasible → chọn recommendation                          |
| **Hạ**    | Integration + Streamlit Dashboard + Tests               | Output của 4 module trên                            | App end-to-end                                  | Bấm Run → Forecast → Bottleneck → Scenario → Simulation → Recommendation hiện trên dashboard |

---

# 2. Quy tắc chung cho cả 5 người

Tất cả AI Agent phải nhận phần này trước task riêng.

```text
PROJECT: D2 Logistics Decision Twin

GOAL:
Build a working end-to-end prototype:

Input
→ Forecast Drivers
→ Future Logistics State
→ Hard Rules + Risk Score
→ Bottleneck Detection
→ Multi-Cause Diagnosis
→ Action Knowledge Base
→ Scenario Generation
→ Static Feasibility
→ SimPy What-if
→ Dynamic Constraint Check
→ KPI Comparison vs S0
→ Robustness
→ Pareto / Decision Mode
→ Recommendation
→ Streamlit Dashboard.

MVP SCOPE:
- 1 target production line: LINE_A
- 2 materials: MAT_A, MAT_B
- Main route R1
- Auxiliary route/resource pool R2
- 5 AMRs total
- Forecast horizon = 60 min
- Interval = 15 min
- Forecast timestamps = +15 / +30 / +45 / +60
- Human remains final decision maker.

DATA ROOT:
data/

Use the PEAK v2 CSV package.

IMPORTANT DATA RULE:
Never use files under validation_only/ for training or runtime decision making.
They are only opened by evaluation/test code after predictions have been produced.

TECH:
Python 3.11
pandas
numpy
scikit-learn
lightgbm
statsmodels
simpy
pyyaml
joblib
streamlit
plotly
pytest

DO NOT ADD:
DRL
LLM decision making
database
FastAPI
OR-Tools in core MVP
external cloud service

CODING RULE:
- No hard-coded recommendation/KPI output.
- All thresholds must come from config YAML.
- All randomness must accept a seed.
- All module public APIs must use shared schemas.
- Never silently read future validation labels.
- Do not change another developer's public interface.
- If another module is unfinished, create a mock implementing the agreed interface.
- Add unit tests for every public function.
- Code must run from project root.
```

## Forecast Scope

Trong MVP, `ForecastPoint` trong `src/common/schemas.py` đại diện cho
forecast drivers của target route `R1`.

- Demand / travel / process P10-P50-P90 trong `ForecastPoint` áp dụng cho R1.
- R2 không yêu cầu một ForecastPoint riêng trong MVP.
- Future state của R2 được xây dựng từ current state, historical/baseline
  behavior và known future events.
- R2 chủ yếu được theo dõi để phát hiện secondary bottleneck khi resource
  được chuyển từ R2 sang R1.

Không tự ý thêm `route_id` hoặc thay đổi `ForecastPoint` nếu chưa thống nhất team.

## Action Parameter Convention

Timing và các tham số cụ thể của action phải được lưu trong
`Action.parameters`. Không thêm field mới vào shared schema.

Ví dụ:

Action(
action_id="A2",
action_type="REASSIGN_AMR",
parameters={
"from_route": "R2",
"to_route": "R1",
"count": 1,
"start_time": "2026-10-08 14:15:00",
"duration_min": 45
}
)

## Repo chung

```text
d2-logistics-decision-twin/
├── config/
│   ├── system.yaml
│   ├── thresholds.yaml
│   ├── actions.yaml
│   └── decision_modes.yaml
├── data/
│   ├── master/
│   ├── history/
│   ├── current/
│   ├── known_future/
│   ├── model_ready/
│   └── validation_only/
├── artifacts/
│   ├── models/
│   ├── forecasts/
│   ├── states/
│   ├── simulations/
│   └── recommendations/
├── src/
│   ├── common/
│   ├── data/
│   ├── forecast/
│   ├── logistics/
│   ├── bottleneck/
│   ├── actions/
│   ├── simulation/
│   ├── evaluation/
│   ├── recommendation/
│   └── orchestration/
├── app/
├── scripts/
└── tests/
```

> **Quy tắc ownership:** mỗi người chỉ chịu trách nhiệm sửa các file trong cột **“Các file chỉnh sửa”** của mình. Nếu cần thay public schema/interface của module khác thì phải báo team trước, không tự sửa.

---

# 3. Phân công chi tiết

| Tên                                                             | Các file chỉnh sửa                                                                                                                                                                                                                                                                                                                                                                                                                           | Các file input sử dụng                                                                                                                                                                                                                                                                                                                                                                                                                                         | Mô tả chi tiết task phải làm                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | Khi thành công chạy gì / test gì                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **HÀ**<br>**Logistics State → Bottleneck → Cause Diagnosis**    | `src/logistics/capacity.py`<br>`src/logistics/queue.py`<br>`src/logistics/buffer.py`<br>`src/logistics/future_state.py`<br><br>`src/bottleneck/hard_rules.py`<br>`src/bottleneck/risk_score.py`<br>`src/bottleneck/detector.py`<br>`src/bottleneck/cause_diagnosis.py`<br><br>`config/thresholds.yaml`<br><br>`tests/test_future_state.py`<br>`tests/test_bottleneck.py`<br>`tests/test_cause_diagnosis.py`                                  | `data/master/material_master.csv`<br>`data/master/route_master.csv`<br>`data/master/resource_master.csv`<br>`data/current/current_state.csv`<br>`data/known_future/known_future_events.csv`<br>`data/known_future/future_production_plan_15min.csv`<br><br>Runtime input từ Dương:<br>`list[ForecastPoint]`                                                                                                                                                    | **Task 1 — Capacity Engine:** implement `calculate_transport_capacity(...)`. Tính `CycleTime = loading + loaded travel + unloading + empty travel`; sau đó tính capacity theo số AMR available, payload, load factor và window 15 phút. Known event như AMR03 maintenance phải trực tiếp làm giảm AMR availability, không đưa cho forecast đoán.<br><br>**Task 2 — Queue Engine:** implement `calculate_queue_state(...)`. Từ `queue_start + demand + capacity` tính `throughput`, `raw_queue`, `queue_end`, `overflow`. Queue không được âm và không vượt staging capacity mà không ghi nhận overflow.<br><br>**Task 3 — Buffer Engine:** implement `update_buffer(...)`. Tính accepted delivery, consumption, next buffer level, unmet consumption, overflow. Buffer luôn nằm trong `[0, max_capacity]`.<br><br>**Task 4 — Future State:** implement `build_future_states(current_state, forecasts, known_events, config)`. Tạo state cho `R1`, `R2` tại `+15/+30/+45/+60`. Expected state dùng P50. Output phải là `list[FutureState]` đúng schema chung.<br><br>**Task 5 — Hard Rules:** đọc threshold từ YAML, tuyệt đối không hard-code. Rule tối thiểu: `DCR_HIGH`, `DCR_CRITICAL`, `QUEUE_GROWTH`, `HIGH_UTILIZATION`, `LOW_BUFFER`, `CRITICAL_LOW_BUFFER`, `BUFFER_OVERFLOW`, `UNMET_CONSUMPTION`. `unmet_consumption > 0` phải đủ khả năng nâng severity lên Critical.<br><br>**Task 6 — Risk Score:** normalize DCR, queue growth, waiting, utilization, buffer risk về `[0,1]`, sau đó tính risk 0–100. Có thể dùng weight `0.30/0.20/0.15/0.20/0.15`. Hard Rule Critical luôn override score.<br><br>**Task 7 — Bottleneck Detector:** implement `detect_bottlenecks(...)`. Với mỗi state tương lai phải trả `WHERE`, `WHEN`, `LEAD TIME`, `SEVERITY`, `RISK SCORE`, `TRIGGERED RULES`, `EVIDENCE` dưới dạng `BottleneckEvent`.<br><br>**Task 8 — Cause Diagnosis:** implement diagnosis rule-based, không gọi là causal ML. Causes tối thiểu: `DEMAND_SPIKE`, `AMR_AVAILABILITY_DROP`, `TRAVEL_TIME_INCREASE`, `PICKING_SLOWDOWN`, `HANDLING_TIME_INCREASE`, `BUFFER_LOW`, `BUFFER_FULL`. Mỗi Cause phải có evidence cụ thể như baseline, forecast, % increase.                                                                                                                                                                                                                                                                                                                                                | Chạy:<br>`pytest tests/test_future_state.py -q`<br>`pytest tests/test_bottleneck.py -q`<br>`pytest tests/test_cause_diagnosis.py -q`<br><br>**Test bắt buộc:**<br>1. Demand < Capacity → queue không tăng vô lý.<br>2. Demand > Capacity → queue tăng.<br>3. Buffer hết → unmet > 0.<br>4. Maintenance AMR → capacity giảm.<br>5. Critical hard rule không bị risk score hạ severity.<br>6. Multi-cause trả được >1 cause.<br><br>**DONE khi:** đưa `ForecastPoint[]` vào và nhận được `FutureState[] → BottleneckEvent[] → Cause[]` mà không cần hard-code output demo.                                                                                                                                                                             |
| **DƯƠNG**<br>**Data Pipeline + Forecast P10/P50/P90**           | `src/data/loader.py`<br>`src/data/validator.py`<br>`src/data/features.py`<br><br>`src/forecast/baseline.py`<br>`src/forecast/quantile_model.py`<br>`src/forecast/service.py`<br>`src/forecast/metrics.py`<br><br>`scripts/train_forecast.py`<br><br>`tests/test_data.py`<br>`tests/test_forecast.py`                                                                                                                                         | **Chính:**<br>`data/model_ready/model_training_15min.csv`<br><br>**Có thể dùng thêm:**<br>`data/history/production_plan_15min.csv`<br>`data/history/production_actual_15min.csv`<br>`data/history/process_history_15min.csv`<br>`data/history/resource_state_15min.csv`<br>`data/history/buffer_state_15min.csv`<br>`data/history/logistics_state_15min.csv`<br><br>**TUYỆT ĐỐI KHÔNG dùng khi train:**<br>`data/validation_only/*`                            | **Task 1 — Loader:** implement `load_training_data(path)`. Parse timestamp, sort theo time, check schema.<br><br>**Task 2 — Validator:** detect duplicate, missing target, negative demand/process time, battery ngoài `[0,100]`, invalid quantities. Không tự ý xóa lỗi im lặng; trả warning/error rõ ràng.<br><br>**Task 3 — Feature Engineering:** tạo tối thiểu `demand_lag_1/2/4`, `travel_lag_1/2/4`, `picking_lag_1/4`, rolling mean demand 4/8 window, travel rolling mean 4, `hour`, `day_of_week`, `shift`, `is_weekend`, `planned_output`, `queue_lag_1`, buffer A/B, AMR available. Tất cả feature chỉ được dùng dữ liệu tại hoặc trước timestamp dự báo; không future leakage.<br><br>**Task 4 — Baseline:** implement Naive, Seasonal Naive, Exponential Smoothing với interface `.fit()` / `.predict()` thống nhất. Baseline dùng làm fallback nếu LightGBM chưa có hoặc lỗi.<br><br>**Task 5 — Quantile Forecast:** train các target: `r1_demand_totes`, `travel_loaded_min`, `travel_empty_min`, `picking_min`, `loading_min`, `unloading_min`. Mỗi target có 3 LightGBM Quantile models `alpha=0.1/0.5/0.9`.<br><br>**Task 6 — Forecast Service:** implement `forecast_future_drivers(now, horizon_min=60, interval_min=15) -> list[ForecastPoint]`. Phải trả đúng `+15/+30/+45/+60`. Mỗi variable có P10/P50/P90. Nếu quantile crossing thì sửa để luôn `P10 <= P50 <= P90`.<br><br>**Task 7 — Metrics:** tính `MAE`, `WAPE`, `Pinball Loss`, `Quantile Coverage`. Train script phải save model bằng `joblib` vào `artifacts/models/`.<br><br>**Task 8 — Fallback:** nếu model file bị xóa hoặc LightGBM fail, `forecast_future_drivers()` vẫn phải hoạt động bằng baseline; pipeline không được crash.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Chạy chính:<br>`python scripts/train_forecast.py`<br><br>Sau đó:<br>`pytest tests/test_data.py -q`<br>`pytest tests/test_forecast.py -q`<br><br>**Test bắt buộc:**<br>1. Timestamp sort đúng.<br>2. Không có future leakage trong feature.<br>3. Forecast trả đúng 4 timestamps.<br>4. Mọi point đều `P10 <= P50 <= P90`.<br>5. Model save/load được.<br>6. Xóa model LightGBM → service vẫn forecast bằng fallback.<br><br>**DONE khi:** một command train từ CSV → build features → train → evaluate → save model; sau đó `forecast_future_drivers()` trả `ForecastPoint[]` hợp lệ mà không cần mở notebook.                                                                                                                                       |
| **PHÚ**<br>**SimPy What-if Digital Twin**                       | `src/simulation/entities.py`<br>`src/simulation/environment.py`<br>`src/simulation/processes.py`<br>`src/simulation/actions.py`<br>`src/simulation/metrics.py`<br>`src/simulation/simulator.py`<br><br>`tests/test_simulation.py`                                                                                                                                                                                                            | `data/master/material_master.csv`<br>`data/master/route_master.csv`<br>`data/master/resource_master.csv`<br>`data/master/station_master.csv`<br><br>`data/history/process_trip_history_clean.csv`<br>`data/history/transport_jobs.csv`<br>`data/history/buffer_state_15min.csv`<br>`data/history/resource_state_15min.csv`<br><br>`data/current/current_state.csv`<br><br>Runtime input:<br>`Scenario` từ Quân<br>`FutureState/Forecast condition` từ Hà/Dương | **Task 1 — Entities:** tạo `MaterialRequest`, `AMR`, `Picker`, `StagingArea`, `Route`, `LineBuffer`, `ProductionLine`. AMR phải chứa id, route, payload, available, battery, busy time.<br><br>**Task 2 — Environment:** tạo SimPy environment và resources: Picker = `simpy.Resource`, AMR pools, staging/buffer = `simpy.Container` hoặc structure tương đương. Capacity phải đọc từ master/config, không hard-code riêng cho demo.<br><br>**Task 3 — Process Flow:** mô phỏng `Request Arrival → wait Picker → Picking → Staging → wait AMR → Loading → Loaded Travel → Unloading → Line Buffer → Empty Return`. Production Consumption phải chạy process riêng và lấy material khỏi buffer theo consumption schedule.<br><br>**Task 4 — Starvation:** nếu consumption cần material nhưng buffer không đủ, track thời điểm starvation start/end, `starvation_minutes`, `unmet_consumption`.<br><br>**Task 5 — Future Conditions:** Expected simulation dùng P50 process/travel/demand. Adverse dùng P90 cho demand/process/travel. Known maintenance apply trực tiếp. Nếu sampling thêm noise thì mọi RNG phải dùng seed truyền vào, không dùng global uncontrolled randomness.<br><br>**Task 6 — Apply Actions:** simulator phải hiểu `PRIORITIZE_REQUEST`, `REASSIGN_AMR`, `ADJUST_REPLENISHMENT_TIME`, `CONSOLIDATE_DELIVERY`. Có handler cho `ALTERNATE_ROUTE` nhưng chỉ chạy nếu scenario đã qua feasibility. Simulator không tự tạo route mới.<br><br>**Task 7 — KPI collector:** output `avg_waiting_time`, `max_waiting_time`, `avg_queue`, `max_queue`, `late_delivery_count`, `throughput`, `service_level`, `starvation_minutes`, `unmet_consumption`, `buffer_overflow`, AMR utilization, `secondary_bottleneck`.<br><br>**Task 8 — Secondary Bottleneck:** sau action như reassign AMR từ R2 → R1, tiếp tục monitor R2. Nếu R1 tốt lên nhưng R2 chuyển thành bottleneck critical thì result phải đánh dấu `secondary_bottleneck=True`.<br><br>**Task 9 — Public API:** implement `run_simulation(current_state, future_condition, scenario, seed=42)` và `run_scenarios(...)`. S0 và tất cả scenario trong một comparison phải dùng cùng seed/future condition.                                                                                                                                                                                                                                                                                                                                              | Chạy:<br>`pytest tests/test_simulation.py -q`<br><br>Có thể thêm smoke run:<br>`python -m src.simulation.simulator` nếu có `__main__` demo.<br><br>**Test bắt buộc:**<br>1. Same input + same seed → same result.<br>2. S0 chạy được.<br>3. Remove 1 AMR không được làm waiting tốt lên vô lý.<br>4. Add capacity không làm throughput giảm vô lý.<br>5. Buffer không âm.<br>6. Maintenance resource không được sử dụng.<br>7. Reassign AMR có thể gây R2 secondary bottleneck.<br>8. Scenario actions thực sự thay simulation, không chỉ đổi label.<br><br>**DONE khi:** truyền `Scenario + current state + future condition` vào và nhận `SimulationResult` thật cho S0/S1/S2/... với KPI reproducible.                                            |
| **QUÂN**<br>**Action → Scenario → Evaluation → Recommendation** | `config/actions.yaml`<br>`config/decision_modes.yaml`<br><br>`src/actions/library.py`<br>`src/actions/scenario_generator.py`<br>`src/actions/feasibility.py`<br><br>`src/evaluation/constraints.py`<br>`src/evaluation/kpi_compare.py`<br>`src/evaluation/pareto.py`<br>`src/evaluation/robustness.py`<br><br>`src/recommendation/builder.py`<br><br>`tests/test_actions.py`<br>`tests/test_evaluation.py`<br>`tests/test_recommendation.py` | Runtime input:<br>`Cause[]` từ Hà<br>`SimulationResult[]` từ Phú<br>`ForecastPoint[]` từ Dương cho robustness<br><br>CSV/config cần đọc:<br>`data/master/route_master.csv`<br>`data/master/resource_master.csv`<br>`data/current/current_state.csv`<br>`config/actions.yaml`<br>`config/decision_modes.yaml`                                                                                                                                                   | **Task 1 — Action Library:** define 5 action: `PRIORITIZE_REQUEST`, `REASSIGN_AMR`, `ALTERNATE_ROUTE`, `ADJUST_REPLENISHMENT_TIME`, `CONSOLIDATE_DELIVERY`. YAML phải chứa causes được address, required params, conflict, disruption, cost.<br><br>**Task 2 — Candidate Retrieval:** implement `get_candidate_actions(causes)`. Ví dụ Demand Spike → Priority / Adjust Replenishment / Consolidate; AMR drop → Reassign; Travel increase → Reassign hoặc Alternate Route nếu có route thật.<br><br>**Task 3 — Alternate Route fix:** dataset hiện chỉ có `R1: Warehouse→LINE_A`, `R2: Warehouse→AUX_AREA`. Do đó `ALTERNATE_ROUTE` hiện phải fail feasibility với `NO_ALTERNATIVE_ROUTE_CONFIGURED`. Không được biến R2 thành alternate route tới LINE_A.<br><br>**Task 4 — Scenario Generator:** implement `generate_scenarios(..., max_scenarios=8)`. `S0=No Action` luôn tồn tại. Sau đó tạo single-action và một số 2-action combination hợp lý. Không brute-force toàn bộ tổ hợp. Pre-rank theo cause coverage + low disruption + compatibility.<br><br>**Task 5 — Static Feasibility:** trước SimPy check resource tồn tại, availability, battery, count, route compatibility, alternate route, action conflict, buffer limits. Không được dùng simulation outcome ở bước này.<br><br>**Task 6 — Dynamic Constraints:** sau SimPy loại scenario gây severe buffer overflow, starvation, critical secondary bottleneck, unacceptable resource overload hoặc late delivery nghiêm trọng ở nơi khác.<br><br>**Task 7 — KPI Comparison:** tất cả so với S0. Lower better: waiting, queue, late, starvation, unmet, disruption. Higher better: throughput, service level. Tính % improvement có epsilon tránh chia 0.<br><br>**Task 8 — Pareto:** loại dominated scenarios bằng non-dominated sorting đơn giản, không OR-Tools.<br><br>**Task 9 — Decision Modes:** implement `balanced`, `service_priority`, `low_disruption`; weight chỉ được áp dụng sau constraints + Pareto.<br><br>**Task 10 — Robustness:** tất cả scenarios chạy Expected=P50; top 3 chạy thêm Favorable=P10 và Adverse=P90. Known maintenance giữ nguyên ở mọi condition. Có thể cho adverse availability giảm thêm 1 AMR nếu config bật, nhưng không dưới 0.<br><br>**Task 11 — Recommendation:** implement `build_decision_package(...)`. Output phải gồm Where/When/Severity, causes+evidence, recommended scenario/actions, start/duration, S0 KPI, recommended KPI, improvement, side effects, robustness. Không dùng LLM để chọn phương án. | Chạy:<br>`pytest tests/test_actions.py -q`<br>`pytest tests/test_evaluation.py -q`<br>`pytest tests/test_recommendation.py -q`<br><br>**Test bắt buộc:**<br>1. S0 luôn có.<br>2. Max scenario <= 8.<br>3. Conflicting actions bị loại.<br>4. Alternate Route bị reject với dataset hiện tại.<br>5. Không đủ AMR → Reassign reject.<br>6. Secondary bottleneck → scenario bị dynamic filter reject hoặc penalize theo config.<br>7. Pareto loại dominated case đúng.<br>8. Decision mode khác nhau có thể rank khác nhau.<br>9. Recommendation luôn kèm baseline S0.<br><br>**DONE khi:** với mock Causes + mock SimulationResult có thể chạy trọn `Cause → Actions → Scenarios → Feasibility → Constraints → Pareto → Robustness → DecisionPackage`. |
| **HẠ**<br>**Integration + Dashboard + Tests**                   | `config/system.yaml`<br><br>`src/common/config.py`<br>`src/common/constants.py` nếu cần<br><br>`src/orchestration/pipeline.py`<br><br>`app/Home.py`<br>`app/pages/1_Control_Tower.py`<br>`app/pages/2_Bottleneck_Cause.py`<br>`app/pages/3_Scenario_Comparison.py`<br>`app/pages/4_Recommendation.py`<br><br>`requirements.txt`<br>`README.md`<br><br>`tests/test_pipeline.py`                                                               | Đọc config:<br>`config/system.yaml`<br>`config/thresholds.yaml`<br>`config/actions.yaml`<br>`config/decision_modes.yaml`<br><br>Runtime output từ 4 module:<br>Dương → `ForecastPoint[]`<br>Hà → `FutureState[]`, `BottleneckEvent[]`, `Cause[]`<br>Quân → `Scenario[]`, `DecisionPackage`<br>Phú → `SimulationResult[]`<br><br>Current input:<br>`data/current/current_state.csv`                                                                             | **Task 1 — Config Loader:** implement `load_config()` để load system/threshold/action/decision YAML. Validate missing field và path.<br><br>**Task 2 — Pipeline Orchestrator:** implement `run_pipeline(decision_mode="balanced", now=None, seed=42)`. Flow đúng thứ tự: `load current → forecast → future state → bottleneck → nếu không có bottleneck return No Action → diagnose → scenario generation → static feasibility → SimPy S0+scenarios → dynamic constraints → KPI compare → Pareto → robustness → recommendation`.<br><br>**Task 3 — Error handling:** nếu module fail phải báo lỗi có ý nghĩa. Không silently replace output bằng hard-coded demo values. Có thể dùng mock chỉ trong development/test, không dùng khi chạy production demo mode.<br><br>**Task 4 — Control Tower:** hiển thị Now/+15/+30/+45/+60, demand P10/P50/P90, capacity, queue, waiting, MAT_A/B buffer, AMR available, risk timeline.<br><br>**Task 5 — Bottleneck & Cause:** card Where/When/Lead Time/Severity/Risk + evidence Demand/Capacity/AMR/Travel/Queue/Buffer + cause cards.<br><br>**Task 6 — Scenario Comparison:** table gồm S0 và scenario khác: Actions, Waiting, Queue, Late, Starvation, Throughput, Service Level, Secondary Bottleneck, Robustness. S0 luôn nằm đầu.<br><br>**Task 7 — Recommendation:** hiển thị Recommended Scenario, actions, expected KPI improvement, side effects, robustness. Nút `APPROVE`, `MODIFY`, `REJECT`, `RUN AGAIN`. Operator decision ghi vào `artifacts/operator_decisions.csv`; không điều khiển AMR thật.<br><br>**Task 8 — Integration Tests:** viết test Normal → No Action; Demand Spike → bottleneck; AMR Failure → Reassign candidate; Multi-cause → combined options; scenario gây secondary bottleneck → không được recommend.<br><br>**Task 9 — README:** ghi setup environment, data placement, train command, test command, dashboard command, architecture và lưu ý synthetic dataset.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Chạy toàn project theo đúng thứ tự:<br><br>`pip install -r requirements.txt`<br><br>`python scripts/train_forecast.py`<br><br>`pytest -q`<br><br>`streamlit run app/Home.py`<br><br>**Integration test bắt buộc:**<br>`pytest tests/test_pipeline.py -q`<br><br>**Demo DONE khi:** trên Streamlit chỉ cần bấm `Run Decision Twin` và hệ thống tự chạy `Input → Forecast → Future State → Bottleneck → Cause → Scenario → SimPy → Evaluation → Robustness → Recommendation`.<br><br>Normal case phải trả `No intervention required` và không chạy SimPy vô ích. Bottleneck case phải hiển thị recommendation sinh từ pipeline thật. Không có KPI/recommendation hard-code.                                                                            |

---

# 4. Điều kiện hoàn thành toàn repo

Repo chỉ được coi là sẵn sàng demo khi chạy thành công theo đúng thứ tự:

```bash
python scripts/train_forecast.py
pytest -q
streamlit run app/Home.py
```

Demo phải chứng minh được ít nhất:

```text
Normal
→ No intervention required

Demand Spike
→ Bottleneck detected
→ Candidate actions generated

AMR Failure
→ REASSIGN_AMR candidate

Multi-cause
→ Multiple causes
→ Combined scenarios

Secondary bottleneck
→ Unsafe scenario rejected / not recommended
```

KPI và recommendation trên dashboard phải thực sự đi qua:

```text
Forecast
→ Future State
→ Bottleneck
→ Cause
→ Scenario
→ SimPy
→ Evaluation
→ Robustness
→ Recommendation
```

**Không hard-code output demo.**
