import os
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


load_dotenv(Path(__file__).with_name(".env"))

SENSORS = ["temperature", "humidity", "distance_cm"]

# Giới hạn vật lý dùng cho bài mô phỏng
BOUNDS = {
    "temperature": (-40, 80),
    "humidity": (0, 100),
    "distance_cm": (2, 400),
}

ORG = os.getenv("INFLUX_ORG")
BUCKET = os.getenv("INFLUX_BUCKET")
URL = os.getenv("INFLUX_URL")
TOKEN = os.getenv("INFLUX_TOKEN")

if not all([ORG, BUCKET, URL, TOKEN]):
    raise SystemExit("Thieu cau hinh InfluxDB trong .env")


def main():
    started = time.perf_counter()
    run_id = uuid.uuid4().hex[:12]

    # Chỉ xử lý các khoảng 5 giây đã kết thúc
    stop = pd.Timestamp.now(tz="UTC").floor("5s")
    start = stop - pd.Timedelta(hours=1)

    query = """
    from(bucket: bucket_name)
      |> range(start: time(v: start_time), stop: time(v: stop_time))
      |> filter(fn: (r) => r._measurement == "sensor_raw")
      |> filter(fn: (r) => r.device_id == "esp32_01")
      |> filter(fn: (r) =>
          r._field == "temperature" or
          r._field == "humidity" or
          r._field == "distance_cm" or
          r._field == "sequence"
      )
      |> pivot(
          rowKey: ["_time"],
          columnKey: ["_field"],
          valueColumn: "_value"
      )
    """

    with InfluxDBClient(
        url=URL, token=TOKEN, org=ORG, timeout=30000
    ) as db:
        print("Dang doc du lieu trong 1 gio gan nhat...")

        tables = db.query_api().query(
            query=query,
            org=ORG,
            params={
                "bucket_name": BUCKET,
                "start_time": start.isoformat(),
                "stop_time": stop.isoformat(),
            },
        )

        rows = [
            record.values
            for table in tables
            for record in table.records
        ]

        if not rows:
            print("Chua co du lieu. Cho collector chay roi thu lai.")
            return

        df = pd.DataFrame(rows)
        df["_time"] = pd.to_datetime(df["_time"], utc=True)

        for name in SENSORS:
            if name not in df.columns:
                df[name] = np.nan
            df[name] = pd.to_numeric(df[name], errors="coerce")

        if "sequence" not in df.columns:
            raise ValueError("Du lieu khong co sequence")

        df = df.sort_values("_time")

        # Một mẫu được xác định bởi thiết bị, lần khởi động và sequence
        before = len(df)
        df = df.drop_duplicates(
            subset=["device_id", "boot_id", "sequence"],
            keep="first",
        )

        print(f"So mau doc duoc: {before}")
        print(f"So mau trung bi loai: {before - len(df)}")
        print(f"Ma dot xu ly: {run_id}")

        points = []

        for (device, boot), group in df.groupby(
            ["device_id", "boot_id"]
        ):
            group = group.sort_values("_time").set_index("_time")

            # Ước tính số sequence bị thiếu giữa các mẫu đã nhận
            sequences = np.sort(group["sequence"].dropna().unique())
            gaps = int(np.maximum(np.diff(sequences) - 1, 0).sum())

            interval = group.index.to_series().diff().dt.total_seconds()
            median_interval = interval.median()

            print(f"\nThiet bi: {device} | boot: {boot}")
            print(f"Khoang lay mau trung vi: {median_interval:.2f} s")
            print(f"Sequence thieu giua cac mau: {gaps}")

            for sensor in SENSORS:
                raw = group[sensor].astype(float)
                low, high = BOUNDS[sensor]

                # Đánh dấu số ngoài giới hạn hoặc không hữu hạn
                invalid = raw.notna() & (
                    ~np.isfinite(raw) | ~raw.between(low, high)
                )
                valid = raw.mask(invalid)

                # Phát hiện ngoại lệ IQR trên cửa sổ dữ liệu đang đọc
                outlier = pd.Series(False, index=raw.index)
                q1 = valid.quantile(0.25)
                q3 = valid.quantile(0.75)
                iqr = q3 - q1

                # Bỏ qua IQR khi quá ít mẫu hoặc IQR bằng 0
                if valid.count() >= 8 and pd.notna(iqr) and iqr > 0:
                    outlier = valid.notna() & (
                        (valid < q1 - 1.5 * iqr)
                        | (valid > q3 + 1.5 * iqr)
                    )

                clean = valid.mask(outlier)

                # Gom dữ liệu theo khoảng 5 giây
                raw_grid = raw.resample("5s").mean()
                clean_grid = clean.resample("5s").mean()

                # Chỉ điền tối đa 2 ô thiếu liên tiếp
                filled = clean_grid.ffill(limit=2)
                imputed = clean_grid.isna() & filled.notna()

                # Trung bình trượt 3 ô; phải đủ cả 3 giá trị
                rolling = filled.rolling(3, min_periods=3).mean()
                delta = filled.diff()

                # Min-max theo dữ liệu sạch của đợt xử lý này
                minimum = filled.min()
                maximum = filled.max()

                if pd.notna(minimum) and maximum > minimum:
                    normalized = (filled - minimum) / (maximum - minimum)
                else:
                    # Chuỗi hằng được quy ước bằng 0; ô thiếu vẫn thiếu
                    normalized = filled * 0.0

                count_grid = raw.resample("5s").size()
                missing_grid = raw.isna().astype(int).resample("5s").sum()
                rejected_grid = (
                    (invalid | outlier).astype(int).resample("5s").sum()
                )

                result = pd.DataFrame({
                    "raw_mean": raw_grid,
                    "clean_value": filled,
                    "rolling_mean": rolling,
                    "delta": delta,
                    "normalized": normalized,
                })

                for timestamp, row in result.iterrows():
                    point = (
                        Point("sensor_processed")
                        .tag("device_id", str(device))
                        .tag("boot_id", str(boot))
                        .tag("sensor", sensor)
                        .tag("run_id", run_id)
                        .time(
                            timestamp.to_pydatetime(),
                            WritePrecision.MS,
                        )
                        .field("sample_count", int(count_grid.loc[timestamp]))
                        .field("missing_count", int(missing_grid.loc[timestamp]))
                        .field("rejected_count", int(rejected_grid.loc[timestamp]))
                        .field("imputed", bool(imputed.loc[timestamp]))
                        .field("valid", bool(pd.notna(row["clean_value"])))
                    )

                    for name, value in row.items():
                        if pd.notna(value) and np.isfinite(value):
                            point.field(name, float(value))

                    if pd.notna(minimum) and pd.notna(maximum):
                        point.field("norm_min", float(minimum))
                        point.field("norm_max", float(maximum))

                    points.append(point)

                print(
                    f"{sensor}: "
                    f"thieu={int(raw.isna().sum())}, "
                    f"ngoai_gioi_han={int(invalid.sum())}, "
                    f"IQR={int(outlier.sum())}, "
                    f"o_da_dien={int(imputed.sum())}"
                )

        with db.write_api(write_options=SYNCHRONOUS) as writer:
            for offset in range(0, len(points), 500):
                writer.write(
                    bucket=BUCKET,
                    org=ORG,
                    record=points[offset:offset + 500],
                )

        elapsed = time.perf_counter() - started
        print(f"\nXU LY OK | Da ghi {len(points)} diem")
        print("Measurement: sensor_processed")
        print(f"run_id: {run_id}")
        print(f"Tong thoi gian doc + xu ly + ghi: {elapsed:.2f} s")
        return run_id


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"LOI: {type(error).__name__}: {error}")