import json
import math
import os
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


# Đọc file .env nằm cạnh collector.py
load_dotenv(Path(__file__).with_name(".env"))

REQUIRED_CONFIG = [
    "INFLUX_URL",
    "INFLUX_TOKEN",
    "INFLUX_ORG",
    "INFLUX_BUCKET",
    "MQTT_BROKER",
    "MQTT_PORT",
    "MQTT_TOPIC",
]

for name in REQUIRED_CONFIG:
    if not os.getenv(name):
        raise SystemExit(f"Thieu {name} trong file .env")

ORG = os.environ["INFLUX_ORG"]
BUCKET = os.environ["INFLUX_BUCKET"]
TOPIC = os.environ["MQTT_TOPIC"]

db = InfluxDBClient(
    url=os.environ["INFLUX_URL"],
    token=os.environ["INFLUX_TOKEN"],
    org=ORG,
    timeout=10000,
)

writer = db.write_api(write_options=SYNCHRONOUS)

SENSOR_FIELDS = ["temperature", "humidity", "distance_cm"]
INTEGER_FIELDS = ["ts_ms", "rssi", "sequence", "uptime_s"]


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("JSON phai la mot object")

    required = [
        "device_id", "boot_id",
        *SENSOR_FIELDS, *INTEGER_FIELDS,
    ]

    for name in required:
        if name not in data:
            raise ValueError(f"Thieu truong {name}")

    for name in ["device_id", "boot_id"]:
        if not isinstance(data[name], str) or not data[name].strip():
            raise ValueError(f"{name} phai la chuoi khong rong")

    for name in INTEGER_FIELDS:
        if type(data[name]) is not int:
            raise ValueError(f"{name} phai la so nguyen")

    if not 1700000000000 <= data["ts_ms"] < 9223372036854:
        raise ValueError("ts_ms khong hop le")

    for name in ["sequence", "uptime_s"]:
        if not 0 <= data[name] <= 9223372036854775807:
            raise ValueError(f"{name} ngoai pham vi")

    if not -200 <= data["rssi"] <= 0:
        raise ValueError("rssi khong hop le")

    for name in SENSOR_FIELDS:
        value = data[name]

        # null được giữ dưới dạng cờ thiếu dữ liệu
        if value is None:
            continue

        if type(value) not in (int, float):
            raise ValueError(f"{name} phai la so hoac null")

        if not math.isfinite(float(value)):
            raise ValueError(f"{name} khong duoc la NaN/Infinity")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"Ket noi MQTT that bai: {reason_code}")
        return

    print("Ket noi MQTT thanh cong")
    client.subscribe(TOPIC)


def on_subscribe(client, userdata, mid, reason_codes, properties):
    if any(code.is_failure for code in reason_codes):
        print(f"Subscribe that bai: {reason_codes}")
    else:
        print(f"Da subscribe: {TOPIC}")
        print("Dang cho du lieu ESP32...\n")


def on_message(client, userdata, message):
    received_ms = time.time_ns() // 1_000_000

    try:
        data = json.loads(message.payload.decode("utf-8"))
        validate(data)
    except (UnicodeDecodeError, ValueError, OverflowError) as error:
        print(f"BO QUA du lieu loi: {error}")
        return

    point = (
        Point("sensor_raw")
        .tag("device_id", data["device_id"])
        .tag("boot_id", data["boot_id"])
        .time(data["ts_ms"], WritePrecision.MS)
        .field("sequence", data["sequence"])
        .field("uptime_s", data["uptime_s"])
        .field("rssi", data["rssi"])
        .field("received_ms", received_ms)
        .field("latency_ms", float(received_ms - data["ts_ms"]))
    )

    for name in SENSOR_FIELDS:
        value = data[name]
        point.field(f"{name}_missing", value is None)

        if value is not None:
            point.field(name, float(value))

    start = time.perf_counter()

    try:
        writer.write(bucket=BUCKET, org=ORG, record=point)
    except Exception as error:
        print(
            f"GHI THAT BAI | sequence={data['sequence']} | "
            f"{type(error).__name__}: {error}"
        )
        return

    write_ms = (time.perf_counter() - start) * 1000

    print(
        f"GHI OK | seq={data['sequence']} | "
        f"temp={data['temperature']} | "
        f"hum={data['humidity']} | "
        f"distance={data['distance_cm']} | "
        f"write={write_ms:.1f} ms"
    )


client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"collector-{uuid.uuid4().hex[:12]}",
)

client.on_connect = on_connect
client.on_subscribe = on_subscribe
client.on_message = on_message
client.reconnect_delay_set(min_delay=1, max_delay=30)


try:
    if not db.ping():
        raise RuntimeError("InfluxDB chua san sang")

    print("InfluxDB dang hoat dong")
    print(f"Bucket: {BUCKET} | Measurement: sensor_raw")

    client.connect(
        os.environ["MQTT_BROKER"],
        int(os.environ["MQTT_PORT"]),
        keepalive=60,
    )
    client.loop_forever()

except KeyboardInterrupt:
    print("\nDa dung collector.")

except Exception as error:
    print(f"LOI: {type(error).__name__}: {error}")

finally:
    client.disconnect()
    writer.close()
    db.close()