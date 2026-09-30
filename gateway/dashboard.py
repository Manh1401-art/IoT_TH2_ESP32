import os
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

from preprocess import main as run_preprocess


load_dotenv(Path(__file__).with_name(".env"))

st.set_page_config(
    page_title="IoT TH2 - ESP32",
    page_icon="📊",
    layout="wide",
)

URL = os.getenv("INFLUX_URL")
TOKEN = os.getenv("INFLUX_TOKEN")
ORG = os.getenv("INFLUX_ORG")
BUCKET = os.getenv("INFLUX_BUCKET")

if not all([URL, TOKEN, ORG, BUCKET]):
    st.error("Thiếu cấu hình InfluxDB trong file .env")
    st.stop()

SENSORS = {
    "temperature": ("Nhiệt độ", "°C"),
    "humidity": ("Độ ẩm", "%RH"),
    "distance_cm": ("Khoảng cách", "cm"),
}

st.title("📊 Giám sát cảm biến ESP32")
st.caption("Bài thực hành 2 • MQTT → Python → InfluxDB → Streamlit")

minutes = st.sidebar.selectbox(
    "Khoảng thời gian hiển thị",
    [15, 30, 60],
    index=1,
)

sensor = st.sidebar.selectbox(
    "Cảm biến trên biểu đồ",
    list(SENSORS),
    format_func=lambda name: SENSORS[name][0],
)

auto_process = st.sidebar.checkbox(
    "Tự xử lý dữ liệu mới mỗi 30 giây",
    value=True,
)

st.sidebar.caption(
    "Giữ InfluxDB, collector và Wokwi chạy. "
    "Phần xử lý tự động hoạt động khi trang này đang mở."
)


def read_data(query, extra=None):
    params = {"bucket_name": BUCKET}
    if extra:
        params.update(extra)

    with InfluxDBClient(
        url=URL,
        token=TOKEN,
        org=ORG,
        timeout=30000,
    ) as db:
        tables = db.query_api().query(
            query=query,
            org=ORG,
            params=params,
        )

        rows = [
            record.values
            for table in tables
            for record in table.records
        ]

    result = pd.DataFrame(rows)

    if not result.empty:
        result["_time"] = pd.to_datetime(result["_time"], utc=True)
        result = result.sort_values("_time")

    return result


def local_times(frame):
    return frame["_time"].dt.tz_convert("Asia/Ho_Chi_Minh")


@st.fragment(run_every="10s")
def show_dashboard():
    try:
        raw = read_data("""
        from(bucket: bucket_name)
          |> range(start: -1h)
          |> filter(fn: (r) => r._measurement == "sensor_raw")
          |> filter(fn: (r) => r.device_id == "esp32_01")
          |> pivot(
              rowKey: ["_time"],
              columnKey: ["_field"],
              valueColumn: "_value"
          )
        """)
    except Exception as error:
        st.error(f"Không đọc được InfluxDB: {error}")
        return

    if raw.empty:
        st.warning("Chưa có dữ liệu trong 1 giờ gần nhất.")
        return

    latest = raw.sort_values("received_ms").iloc[-1]
    now = pd.Timestamp.now(tz="UTC")

    received_time = pd.to_datetime(
        int(latest["received_ms"]),
        unit="ms",
        utc=True,
    )
    age = (now - received_time).total_seconds()

    columns = st.columns(3)

    for column, (name, (label, unit)) in zip(columns, SENSORS.items()):
        value = latest.get(name)
        text = "Thiếu dữ liệu" if pd.isna(value) else f"{value:.2f} {unit}"
        column.metric(label, text)

    received_local = received_time.tz_convert("Asia/Ho_Chi_Minh")
    device_local = latest["_time"].tz_convert("Asia/Ho_Chi_Minh")

    st.caption(
        f"Python nhận gần nhất: {received_local:%H:%M:%S} "
        f"• Thời gian ESP32: {device_local:%H:%M:%S} "
        f"• Sequence: {latest.get('sequence', '?')}"
    )

    if age > 20:
        st.warning(
            f"Mẫu mới nhất đã cách hiện tại {age:.0f} giây. "
            "Kiểm tra Wokwi và collector nếu đang cần dữ liệu trực tiếp."
        )
    elif age < -5:
        st.warning("Thời gian mẫu nằm trong tương lai. Cần kiểm tra đồng hồ.")

    # Chạy xử lý khi có mẫu mới, cách lần thử trước ít nhất 30 giây
    stamp = latest["_time"].isoformat()
    last_attempt = st.session_state.get("last_attempt", 0.0)
    has_new_data = stamp != st.session_state.get("processed_stamp")

    if (
        auto_process
        and has_new_data
        and time.monotonic() - last_attempt >= 30
    ):
        st.session_state["last_attempt"] = time.monotonic()

        try:
            with st.spinner("Đang xử lý dữ liệu mới..."):
                run_id = run_preprocess()

            if run_id:
                st.session_state["run_id"] = run_id
                st.session_state["processed_stamp"] = stamp
                st.session_state["processed_at"] = pd.Timestamp.now(
                    tz="Asia/Ho_Chi_Minh"
                )
                st.session_state.pop("process_error", None)
            else:
                st.session_state["process_error"] = (
                    "Chưa nhận được mã đợt xử lý. "
                    "Kiểm tra dòng return run_id trong preprocess.py."
                )
        except Exception as error:
            st.session_state["process_error"] = str(error)

    if st.session_state.get("process_error"):
        st.error("Lỗi xử lý: " + st.session_state["process_error"])

    processed = pd.DataFrame()
    run_id = st.session_state.get("run_id")

    if run_id:
        try:
            processed = read_data("""
            from(bucket: bucket_name)
              |> range(start: -1h)
              |> filter(fn: (r) => r._measurement == "sensor_processed")
              |> filter(fn: (r) => r.device_id == "esp32_01")
              |> filter(fn: (r) => r.run_id == selected_run)
              |> filter(fn: (r) => r.sensor == selected_sensor)
              |> pivot(
                  rowKey: ["_time"],
                  columnKey: ["_field"],
                  valueColumn: "_value"
              )
            """, {
                "selected_run": run_id,
                "selected_sensor": sensor,
            })
        except Exception as error:
            st.error(f"Không đọc được dữ liệu sau xử lý: {error}")

    cutoff = now - pd.Timedelta(minutes=minutes)
    raw_view = raw[raw["_time"] >= cutoff].copy()

    if not processed.empty:
        processed = processed[processed["_time"] >= cutoff].copy()

    label, unit = SENSORS[sensor]
    st.subheader(f"{label}: trước và sau xử lý")

    fig = go.Figure()

    # Tách từng boot để không nối đường qua các lần khởi động
    for index, (_, group) in enumerate(raw_view.groupby("boot_id")):
        if sensor in group.columns:
            fig.add_trace(go.Scatter(
                x=local_times(group),
                y=group[sensor],
                name="Dữ liệu gốc",
                legendgroup="raw",
                showlegend=index == 0,
                mode="lines+markers",
                line=dict(color="#94a3b8", width=1),
                marker=dict(size=4),
                connectgaps=False,
            ))

    if not processed.empty:
        for field, title, color in [
            ("clean_value", "Sau làm sạch", "#22c55e"),
            ("rolling_mean", "Trung bình trượt", "#f59e0b"),
        ]:
            if field not in processed.columns:
                continue

            for index, (_, group) in enumerate(
                processed.groupby("boot_id")
            ):
                fig.add_trace(go.Scatter(
                    x=local_times(group),
                    y=group[field],
                    name=title,
                    legendgroup=field,
                    showlegend=index == 0,
                    mode="lines",
                    line=dict(color=color, width=3),
                    connectgaps=False,
                ))

    fig.update_layout(
        height=430,
        xaxis_title="Thời gian Việt Nam",
        yaxis_title=f"{label} ({unit})",
        hovermode="x unified",
        legend=dict(orientation="h"),
        margin=dict(l=20, r=20, t=30, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    if run_id:
        finished = st.session_state["processed_at"]
        st.caption(
            f"Đợt xử lý: {run_id} • Hoàn thành lúc {finished:%H:%M:%S}. "
            "Dữ liệu xử lý có thể chậm hơn dữ liệu gốc khoảng 30 giây."
        )

    if not processed.empty:
        st.subheader("Kết quả xử lý gần nhất")

        wanted = [
            "_time", "raw_mean", "clean_value",
            "rolling_mean", "delta", "normalized",
            "imputed", "valid",
        ]
        available = [
            column for column in wanted if column in processed.columns
        ]

        table = processed[available].tail(20).copy()
        table["_time"] = (
            table["_time"]
            .dt.tz_convert("Asia/Ho_Chi_Minh")
            .dt.strftime("%H:%M:%S")
        )
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.info("Bật tự xử lý để hiển thị kết quả trước/sau.")

    st.caption(
        "normalized: chuẩn hóa min-max • imputed: đã điền giá trị thiếu "
        "• valid: có giá trị sau làm sạch"
    )


show_dashboard()