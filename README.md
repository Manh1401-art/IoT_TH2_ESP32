# Bài thực hành 2 – Thu thập và tiền xử lý dữ liệu IoT

## 1. Giới thiệu

Hệ thống sử dụng ESP32 mô phỏng trên Wokwi để đọc nhiệt độ,
độ ẩm và khoảng cách. Dữ liệu được truyền bằng MQTT,
thu thập bằng Python, lưu vào InfluxDB 2 và hiển thị trên Streamlit.

Luồng dữ liệu:

ESP32 → MQTT broker → collector.py → InfluxDB
→ preprocess.py → InfluxDB → dashboard.py

## 2. Thành phần mã nguồn

| File | Chức năng |
|---|---|
| src/main.cpp | Đọc cảm biến, đồng bộ NTP, gửi JSON qua MQTT |
| diagram.json | Sơ đồ mạch Wokwi |
| platformio.ini | Cấu hình board, framework và thư viện firmware |
| wokwi.toml | Cấu hình firmware cho Wokwi |
| gateway/collector.py | Kiểm tra dữ liệu MQTT và ghi InfluxDB |
| gateway/preprocess.py | Làm sạch, lấy mẫu lại và tính các đặc trưng |
| gateway/dashboard.py | Hiển thị dữ liệu gốc và kết quả xử lý |
| gateway/.env.example | Cấu hình mẫu |
| gateway/requirements.txt | Thư viện Python và phiên bản |
| .gitignore | Loại cấu hình bí mật và file sinh tự động khỏi Git |

## 3. Phần cứng mô phỏng

| Thiết bị | Chân ESP32 |
|---|---|
| DHT22 DATA | GPIO 15 |
| HC-SR04 TRIG | GPIO 5 |
| HC-SR04 ECHO | GPIO 19 |
| LED | GPIO 2 |

Chu kỳ lấy mẫu dự kiến: 5 giây theo đồng hồ thiết bị.

Wi-Fi mô phỏng: Wokwi-GUEST, không có mật khẩu.

MQTT broker: broker.hivemq.com, cổng 1883.

Topic mặc định:
ptit/iot_lab2/manh_7c91/esp32_01/telemetry

## 4. Chuẩn bị môi trường

- VS Code.
- Extension PlatformIO IDE.
- Extension Wokwi và quyền sử dụng Wokwi trong VS Code.
- Python 3.12.
- InfluxDB 2.x hỗ trợ truy vấn Flux.
- Kết nối Internet cho MQTT và NTP.

Môi trường thực hành sử dụng InfluxDB chạy trực tiếp trên Windows.

## 5. Cấu hình InfluxDB

1. Chạy influxd.exe và giữ tiến trình hoạt động.
2. Truy cập http://localhost:8086.
3. Trong lần cài đặt đầu tiên, tạo tài khoản quản trị.
4. Tạo organization PTIT và bucket iot_lab2.
5. Tạo API token có quyền đọc và ghi bucket này.

Nếu dùng organization hoặc bucket khác, cập nhật file .env tương ứng.

Không đưa API token thật lên GitHub.

## 6. Cài đặt Python

Mở terminal tại thư mục gốc dự án:

```powershell
cd gateway
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Tạo file cấu hình cho lần cài đặt đầu tiên:

```powershell
Copy-Item .env.example .env
```

Nếu đã có .env đang hoạt động, giữ file đó và bỏ qua lệnh sao chép.

Mở .env và điền INFLUX_TOKEN. Kiểm tra URL, organization,
bucket và cấu hình MQTT.

Nếu thay đổi topic MQTT, cần sửa cả .env và MQTT_TOPIC
trong src/main.cpp, sau đó build lại firmware.

## 7. Chạy hệ thống

### Bước 1: Khởi động InfluxDB

Chạy influxd.exe.

Kiểm tra giao diện:
http://localhost:8086

### Bước 2: Chạy collector

Mở terminal tại gateway:

```powershell
.\.venv\Scripts\python.exe collector.py
```

Chờ thông báo kết nối MQTT và subscribe thành công.

### Bước 3: Build và chạy ESP32

1. Mở thư mục gốc dự án bằng VS Code.
2. Chọn PlatformIO: Build và chờ SUCCESS.
3. Nhấn Ctrl + Shift + P.
4. Chọn Wokwi: Start Simulator.
5. Chờ ESP32 kết nối Wi-Fi, đồng bộ NTP và MQTT.

Giữ tab mô phỏng hiển thị trong khi kiểm thử.

Collector ghi thành công sẽ in dòng GHI OK cùng sequence,
giá trị cảm biến và thời gian ghi InfluxDB.

### Bước 4: Chạy dashboard

Mở terminal khác tại gateway:

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Truy cập:
http://localhost:8501

Bật "Tự xử lý dữ liệu mới mỗi 30 giây".

Dashboard kiểm tra dữ liệu định kỳ 10 giây. Khi có dữ liệu mới,
phần tiền xử lý được gọi với khoảng cách giữa các lần thử
ít nhất 30 giây.

### Chạy tiền xử lý thủ công

Có thể chạy riêng:

```powershell
.\.venv\Scripts\python.exe preprocess.py
```

Không cần chạy lệnh này khi dashboard đang tự xử lý.

Dashboard hiện sử dụng run_id của lần xử lý do chính phiên
dashboard gọi; không tự chọn run_id từ lần chạy thủ công.

## 8. Dữ liệu và xử lý

### Dữ liệu gốc

Measurement: sensor_raw.

Tags chính:
- device_id
- boot_id

Các field gồm:
- temperature, humidity, distance_cm
- sequence, uptime_s, rssi
- received_ms, latency_ms
- Cờ thiếu dữ liệu của từng cảm biến

Thời gian của điểm dữ liệu sử dụng ts_ms từ ESP32.

Collector kiểm tra cấu trúc JSON, trường bắt buộc và kiểu dữ liệu.
Giá trị cảm biến null được biểu diễn bằng cờ thiếu dữ liệu.

### Tiền xử lý

- Đọc dữ liệu trong cửa sổ một giờ.
- Loại bản ghi lặp theo device_id, boot_id và sequence trong tập đọc.
- Kiểm tra giới hạn vật lý và phát hiện ngoại lệ bằng IQR.
- Lấy mẫu lại theo cửa sổ 5 giây.
- Điền tiến tối đa hai cửa sổ thiếu liên tiếp.
- Tính trung bình trượt ba cửa sổ và độ biến thiên.
- Chuẩn hóa min-max theo từng đợt xử lý.

Kết quả lưu vào measurement sensor_processed.

Tags gồm device_id, boot_id, sensor và run_id.

Các field kết quả gồm raw_mean, clean_value, rolling_mean,
delta, normalized, imputed và valid.

Mỗi đợt xử lý có run_id riêng. Các đợt có thể chứa
những khoảng dữ liệu thời gian trùng nhau.

## 9. Kiểm tra hoạt động

1. Thay đổi nhiệt độ hoặc độ ẩm trên DHT22 trong Wokwi.
2. Thay đổi khoảng cách trên HC-SR04.
3. Kiểm tra giá trị mới trong log collector.
4. Kiểm tra các ô giá trị trên dashboard.
5. Chờ xử lý tự động rồi quan sát biểu đồ trước/sau xử lý.

Dashboard tách đường theo boot_id để tránh nối các lần
khởi động ESP32.

## 10. Lưu ý về thời gian và giới hạn

- Firmware đồng bộ NTP định kỳ 30 giây.
- Mô phỏng có thể chạy chậm hoặc tạm dừng khi không hiển thị.
- received_ms là thời điểm Python nhận bản tin.
- latency_ms = received_ms - ts_ms còn chịu ảnh hưởng của
  chênh lệch đồng hồ; chưa thể coi là độ trễ mạng thuần túy.
- write trong log collector là thời gian gọi ghi đồng bộ InfluxDB.
- MQTT publish sử dụng QoS 0; mẫu khi mất kết nối không được
  lưu đệm để gửi lại.
- Việc điền thiếu và làm sạch có thể chưa tạo ra khác biệt rõ
  nếu dữ liệu đầu vào luôn hợp lệ và ổn định.

## 11. Dừng hệ thống

- Nhấn Ctrl + C trong terminal collector.
- Nhấn Ctrl + C trong terminal dashboard.
- Dừng Wokwi.
- Dừng InfluxDB khi không còn sử dụng.