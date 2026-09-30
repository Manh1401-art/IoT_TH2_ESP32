import json
import uuid
from datetime import datetime

import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
PORT = 1883
TOPIC = "ptit/iot_lab2/manh_7c91/esp32_01/telemetry"


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
    try:
        data = json.loads(message.payload.decode("utf-8"))

        if not isinstance(data, dict):
            raise ValueError("JSON phai la mot object")

        required = [
            "device_id", "boot_id", "ts_ms",
            "temperature", "humidity", "distance_cm",
            "rssi", "sequence", "uptime_s"
        ]

        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"Thieu truong: {missing}")

        received_at = datetime.now().astimezone().isoformat(
            timespec="seconds"
        )

        print(f"[{received_at}] Nhan du lieu:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        print("-" * 50)

    except (UnicodeDecodeError, ValueError) as error:
        print(f"Du lieu khong hop le: {error}")


client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id=f"iot-th2-python-{uuid.uuid4().hex[:12]}"
)

client.on_connect = on_connect
client.on_subscribe = on_subscribe
client.on_message = on_message
client.reconnect_delay_set(min_delay=1, max_delay=30)

try:
    print(f"Dang ket noi {BROKER}:{PORT}...")
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_forever()
except KeyboardInterrupt:
    print("\nDa dung chuong trinh.")
except OSError as error:
    print(f"Loi ket noi: {error}")
finally:
    client.disconnect()