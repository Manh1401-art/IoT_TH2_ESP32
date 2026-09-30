#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHTesp.h>
#include <math.h>
#include <time.h>
#include <sys/time.h>
#include <esp_system.h>
#include <esp_sntp.h>

// ================= CAU HINH =================

const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASSWORD = "";

const char* MQTT_SERVER = "broker.hivemq.com";
const int MQTT_PORT = 1883;

const char* MQTT_TOPIC =
    "ptit/iot_lab2/manh_7c91/esp32_01/telemetry";

const char* DEVICE_ID = "esp32_01";

const int DHT_PIN = 15;
const int TRIG_PIN = 5;
const int ECHO_PIN = 19;
const int LED_PIN = 2;

const unsigned long SEND_INTERVAL_MS = 5000;

// ================= DOI TUONG =================

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
DHTesp dht;

unsigned long lastSample = 0;
unsigned long lastWifiAttempt = 0;
unsigned long lastMqttAttempt = 0;
unsigned long sequenceNo = 0;

char bootId[24];
char clientId[64];

// ================= DOC KHOANG CACH =================

float readDistanceCm() {
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);

    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    unsigned long duration =
        pulseIn(ECHO_PIN, HIGH, 30000);

    if (duration == 0) {
        return NAN;
    }

    return duration * 0.0343f / 2.0f;
}

// Chuyen gia tri loi thanh null de JSON van hop le
void numberOrNull(float value, char* output, size_t size) {
    if (isfinite(value)) {
        snprintf(output, size, "%.2f", value);
    } else {
        snprintf(output, size, "null");
    }
}

// ================= DUY TRI KET NOI =================

void maintainConnections() {
    unsigned long now = millis();

    if (WiFi.status() != WL_CONNECTED) {
        if (now - lastWifiAttempt >= 10000) {
            lastWifiAttempt = now;
            Serial.println("Reconnecting WiFi...");
            WiFi.reconnect();
        }
        return;
    }

    if (!mqttClient.connected()) {
        if (now - lastMqttAttempt >= 3000) {
            lastMqttAttempt = now;

            Serial.print("Connecting MQTT... ");

            if (mqttClient.connect(clientId)) {
                Serial.println("OK");
            } else {
                Serial.printf(
                    "FAILED, rc=%d\n",
                    mqttClient.state()
                );
            }
        }
    }

    if (mqttClient.connected()) {
        mqttClient.loop();
    }
}

// ================= LAY MAU VA GUI =================

void sampleAndPublish() {
    // Tang theo moi lan lay mau, ke ca khi mat mang
    sequenceNo++;

    TempAndHumidity data = dht.getTempAndHumidity();

    if (dht.getStatus() != 0) {
        data.temperature = NAN;
        data.humidity = NAN;
    }

    float distance = readDistanceCm();

    // Lay thoi gian UTC sau khi doc cam bien
    struct timeval tv;
    gettimeofday(&tv, nullptr);

    if (tv.tv_sec < 1700000000) {
        Serial.printf(
            "seq=%lu | Waiting for NTP time\n",
            sequenceNo
        );
        return;
    }

    unsigned long long timestampMs =
        (unsigned long long)tv.tv_sec * 1000ULL
        + (unsigned long long)tv.tv_usec / 1000ULL;

    if (WiFi.status() != WL_CONNECTED ||
        !mqttClient.connected()) {
        Serial.printf(
            "seq=%lu | Offline - sample not sent\n",
            sequenceNo
        );
        return;
    }

    char temperatureText[24];
    char humidityText[24];
    char distanceText[24];

    numberOrNull(
        data.temperature,
        temperatureText,
        sizeof(temperatureText)
    );

    numberOrNull(
        data.humidity,
        humidityText,
        sizeof(humidityText)
    );

    numberOrNull(
        distance,
        distanceText,
        sizeof(distanceText)
    );

    char payload[512];

    int length = snprintf(
        payload,
        sizeof(payload),
        "{\"device_id\":\"%s\","
        "\"boot_id\":\"%s\","
        "\"ts_ms\":%llu,"
        "\"temperature\":%s,"
        "\"humidity\":%s,"
        "\"distance_cm\":%s,"
        "\"rssi\":%d,"
        "\"sequence\":%lu,"
        "\"uptime_s\":%lu}",
        DEVICE_ID,
        bootId,
        timestampMs,
        temperatureText,
        humidityText,
        distanceText,
        (int)WiFi.RSSI(),
        sequenceNo,
        millis() / 1000UL
    );

    if (length < 0 || length >= (int)sizeof(payload)) {
        Serial.println("Payload too large - skip");
        return;
    }

    bool ok = mqttClient.publish(
        MQTT_TOPIC,
        payload,
        false
    );

    Serial.printf(
        "%s | publish=%s\n",
        payload,
        ok ? "OK" : "FAILED"
    );

    if (ok) {
        digitalWrite(LED_PIN, HIGH);
        delay(80);
        digitalWrite(LED_PIN, LOW);
    }
}

// ================= KHOI TAO =================
void onTimeSync(struct timeval* tv) {
    Serial.printf(
        "[NTP] Dong bo thanh cong | UTC epoch=%llu ms\n",
        (unsigned long long)tv->tv_sec * 1000ULL
        + (unsigned long long)tv->tv_usec / 1000ULL
    );
}

void setup() {
    Serial.begin(115200);

    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    pinMode(LED_PIN, OUTPUT);

    digitalWrite(TRIG_PIN, LOW);
    digitalWrite(LED_PIN, LOW);

    dht.setup(DHT_PIN, DHTesp::DHT22);

    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD, 6);

    // Tao ma phien moi khi ESP32 khoi dong
    snprintf(
        bootId,
        sizeof(bootId),
        "%08lx%08lx",
        (unsigned long)esp_random(),
        (unsigned long)esp_random()
    );

    snprintf(
        clientId,
        sizeof(clientId),
        "ptit-manh-7c91-%s",
        bootId
    );

    mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
    mqttClient.setSocketTimeout(5);

    if (!mqttClient.setBufferSize(768)) {
        Serial.println("Cannot allocate MQTT buffer");
    }

    // Ghi log moi khi dong bo NTP thanh cong
    sntp_set_time_sync_notification_cb(onTimeSync);

    // Dong bo lai moi 30 giay
    sntp_set_sync_interval(30000);

    configTime(
        0,
        0,
        "pool.ntp.org",
        "time.google.com"
    );

    Serial.println("\n=== IoT TH2 ===");
    Serial.printf("Device: %s\n", DEVICE_ID);
    Serial.printf("Boot ID: %s\n", bootId);
    Serial.printf("Topic: %s\n", MQTT_TOPIC);
    Serial.println("Connecting WiFi...");
}

// ================= VONG LAP CHINH =================

void loop() {
    maintainConnections();

    unsigned long now = millis();

    if (now - lastSample >= SEND_INTERVAL_MS) {
        lastSample = now;
        sampleAndPublish();
    }

    delay(2);
}