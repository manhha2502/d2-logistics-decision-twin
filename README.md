# D2 Logistics Decision Twin

Prototype hỗ trợ operator dự báo điểm nghẽn logistics, mô phỏng phương án can thiệp và so sánh kết quả trước khi ra quyết định. Dashboard dùng **Streamlit**; dữ liệu PEAK v2 trong repo là dữ liệu mô phỏng.

## Chạy dashboard

Yêu cầu **Python 3.11 hoặc 3.12**. Mở PowerShell tại thư mục gốc của repo rồi chạy:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/train_forecast.py
.\.venv\Scripts\python.exe -m streamlit run app/Home.py
```

Giữ cửa sổ PowerShell này mở và truy cập **http://localhost:8501** trong trình duyệt. Nhấn `Ctrl+C` trong PowerShell để dừng dashboard.

Lệnh train tạo model tại `artifacts/models/forecast_models.joblib`. Dashboard vẫn có thể dùng baseline dự báo khi chưa có model, nhưng nên train trước để demo đúng quy trình.

Nếu đã kích hoạt virtual environment, có thể dùng lệnh ngắn `streamlit run app/Home.py`. Trên macOS/Linux, thay `.\.venv\Scripts\python.exe` bằng `.venv/bin/python`.

### Thao tác trên dashboard

1. Giữ thời điểm dữ liệu mặc định **2026-10-08 14:00:00** và seed **42**.
2. Chọn **Cách chọn phương án**, rồi bấm **Chạy phân tích** ở thanh bên.
3. Xem kết quả theo thứ tự: **Tổng quan vận hành** → **Điểm nghẽn và nguyên nhân** → **So sánh phương án** → **Đề xuất hành động**.
4. Ở trang đề xuất, operator có thể **Chấp thuận**, **Yêu cầu sửa** hoặc **Từ chối**. Nút **Chạy lại** chạy pipeline với cấu hình đang chọn.

Thời điểm mặc định khớp các CSV trong repo. Nếu đổi thời điểm, cần chuẩn bị `current_state.csv` và dữ liệu kế hoạch/sự kiện tương ứng; chỉ sửa ô thời gian không tạo ra dữ liệu mới.

## Demo năm ca kiểm thử

Dashboard chạy trên snapshot PEAK v2 mặc định. Năm ca có thay đổi đầu vào được chạy **riêng trong terminal**:

```powershell
.\.venv\Scripts\python.exe scripts/demo_cases.py
```

Script in trạng thái, số điểm nghẽn, nguyên nhân, số phương án, phương án được chọn và lý do loại phương án của từng ca:

| Ca | Nội dung kiểm tra |
| --- | --- |
| `normal` | Không cần can thiệp. |
| `demand_spike` | Nhu cầu tăng và hệ thống phát hiện điểm nghẽn. |
| `amr_failure` | AMR thiếu khả dụng; xem xét điều chuyển AMR. |
| `multi_cause` | Nhiều nguyên nhân và phương án kết hợp. |
| `secondary_bottleneck` | Kiểm tra nguy cơ chuyển điểm nghẽn sang R2. |

Các thay đổi đầu vào của năm ca nằm trong [config/demo_cases.yaml](config/demo_cases.yaml). Script dùng module forecast, mô phỏng và lựa chọn phương án thật; không gán sẵn KPI hay kết luận. Script không chuyển dashboard sang ca khác và không sửa CSV gốc.

## Đọc kết quả

- **S0** là phương án giữ nguyên hiện trạng. **S1, S2, …** là các phương án can thiệp được tạo từ nguyên nhân phát hiện được; số lượng phụ thuộc dữ liệu và ràng buộc. Nếu không cần can thiệp, pipeline dừng trước bước mô phỏng.
- Có điểm nghẽn không đồng nghĩa phải can thiệp: hệ thống có thể chọn **S0** khi các phương án còn lại vi phạm ràng buộc an toàn hoặc có kết quả kém hơn.
- Bảng **So sánh phương án** cho thấy cả phương án bị loại và lý do loại. Đề xuất cuối cùng là phương án được chọn trong tập phương án khả thi, không phải phương án tối ưu cho mọi can thiệp có thể có.
- Ba cách chọn phương án là **Cân bằng tổng thể**, **Ưu tiên mức đáp ứng** và **Hạn chế xáo trộn**. Chúng thay đổi cách xếp hạng sau kiểm tra ràng buộc; KPI mô phỏng của cùng một phương án, cùng dữ liệu và seed không đổi.
- P10, P50 và P90 là các điều kiện dự báo/mô phỏng. Các chỉ số trên dashboard là kết quả mô phỏng, không phải số liệu vận hành sau khi thực hiện hành động.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Để kiểm tra riêng pipeline thật và năm ca demo:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_real_pipeline.py tests/test_demo_cases.py -q
```

## Luồng xử lý

```text
CSV hiện tại + kế hoạch + sự kiện đã biết
  → Forecast P10/P50/P90 (+15, +30, +45, +60 phút)
  → Trạng thái logistics tương lai của R1/R2
  → Phát hiện điểm nghẽn và chẩn đoán nguyên nhân
  → Tạo phương án, kiểm tra tính khả thi
  → SimPy mô phỏng S0 và các phương án
  → Kiểm tra ràng buộc, so sánh KPI, độ ổn định
  → Xếp hạng và đề xuất cho operator
```

Phạm vi MVP: **LINE_A**, vật tư **MAT_A/MAT_B**, tuyến chính **R1**, tuyến phụ/pool tài nguyên **R2**, **5 AMR**, dự báo **60 phút** theo bước **15 phút**. Entry point của pipeline là `src.orchestration.pipeline.run_pipeline(...)`; giao diện bắt đầu tại [app/Home.py](app/Home.py).

## Dữ liệu và kết quả lưu trên máy

CSV PEAK v2 đã nằm trong [data/](data/):

| Thư mục | Vai trò |
| --- | --- |
| `data/master/`, `data/history/`, `data/model_ready/` | Master data, lịch sử và dữ liệu train. |
| `data/current/`, `data/known_future/` | Snapshot và đầu vào runtime. |
| `data/validation_only/` | Chỉ dùng đánh giá sau dự báo; không dùng để train hay ra quyết định runtime. |

Mỗi lần chạy dashboard tạo JSON trong `artifacts/recommendations/<run_id>.json`. Quyết định của operator được ghi vào `artifacts/operator_decisions.csv`; **Yêu cầu sửa** cần nội dung ghi chú. Các file sinh ra được Git bỏ qua.

Dữ liệu là **synthetic**. Hệ thống hỗ trợ quyết định và ghi audit; không gửi lệnh điều khiển đến AMR thật.

## Khi không mở được dashboard

| Hiện tượng | Cách kiểm tra |
| --- | --- |
| `ModuleNotFoundError` | Cài lại bằng đúng Python trong `.venv`: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`. |
| PowerShell không nhận `streamlit` | Dùng `.\.venv\Scripts\python.exe -m streamlit run app/Home.py`. |
| Cổng 8501 đang được dùng | Thêm `--server.port 8502` vào lệnh chạy và mở `http://localhost:8502`. |
| Dashboard báo thiếu dữ liệu | Chạy từ thư mục gốc và kiểm tra các đường dẫn trong [config/system.yaml](config/system.yaml). |
