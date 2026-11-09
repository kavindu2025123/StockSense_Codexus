/*
 * StockSense ESP32 Telemetry Node - Wokwi Simulation Firmware
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// Configuration Parameters
const char* WIFI_SSID       = "Wokwi-GUEST";
const char* WIFI_PASSWORD   = "";
const char* MQTT_BROKER = "broker.hivemq.com";
const int   MQTT_PORT       = 1883;
const char* MQTT_CLIENT_ID  = "StockSense_ESP32_Node_01";
const char* MQTT_TOPIC = "stocksense/kavindu/telemetry";

const int LOAD_CELL_PIN     = 34;
const float EMA_ALPHA       = 0.2;
const unsigned long PUB_INT = 3000;

WiFiClient espClient;
PubSubClient mqttClient(espClient);

float filtered_weight = 0.0;
bool is_first_read = true;
unsigned long last_pub_time = 0;

// In-Memory Queue for Wokwi Simulation
String offlineQueue[10];
int queueCount = 0;

const char* MOCK_RFID_TAGS[] = {
    "E200001700000000",
    "E200001700000001",
    "E200001700000002",
    "E200001700000003"
};
int rfid_index = 0;

void connectWiFi() {
    if (WiFi.status() == WL_CONNECTED) return;
    
    Serial.print("[NETWORK] Connecting to WiFi SSID: ");
    Serial.println(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\n[NETWORK] WiFi Connected successfully!");
        Serial.print("[NETWORK] IP Address: ");
        Serial.println(WiFi.localIP());
    }
}

void flushOfflineQueue() {
    if (queueCount == 0) return;
    Serial.println("[STORAGE] Offloading cached telemetry to MQTT broker...");
    for (int i = 0; i < queueCount; i++) {
        if (mqttClient.publish(MQTT_TOPIC, offlineQueue[i].c_str())) {
            Serial.print("[STORAGE] Flushed queued record: ");
            Serial.println(offlineQueue[i]);
            delay(100);
        }
    }
    queueCount = 0;
    Serial.println("[STORAGE] Offline queue successfully emptied.");
}

void connectMQTT() {
    Serial.print("[MQTT] Connecting to Broker: ");
    Serial.println(MQTT_BROKER);
    
    if (mqttClient.connect(MQTT_CLIENT_ID)) {
        Serial.println("[MQTT] Connected Successfully!");
        flushOfflineQueue();
    } else {
        Serial.print("[MQTT] Reconnect Failed, rc=");
        Serial.print(mqttClient.state());
        Serial.println(" -> Buffering payload.");
    }
}

float readAndFilterSensor() {
    int raw_adc = analogRead(LOAD_CELL_PIN);
    float raw_weight = (raw_adc / 4095.0) * 5000.0;
    
    if (is_first_read) {
        filtered_weight = raw_weight;
        is_first_read = false;
    } else {
        filtered_weight = (EMA_ALPHA * raw_weight) + ((1.0 - EMA_ALPHA) * filtered_weight);
    }
    return raw_weight;
}

void saveOfflinePayload(const String& payload) {
    if (queueCount < 10) {
        offlineQueue[queueCount++] = payload;
        Serial.println("[STORAGE] Telemetry saved to offline queue (RAM Buffer).");
    }
}

void publishTelemetry() {
    float raw_weight = readAndFilterSensor();
    const char* current_rfid = MOCK_RFID_TAGS[rfid_index];
    rfid_index = (rfid_index + 1) % 4;

    StaticJsonDocument<256> doc;
    doc["device_id"]       = MQTT_CLIENT_ID;
    doc["timestamp_ms"]    = millis();
    doc["raw_weight_g"]    = round(raw_weight * 100.0) / 100.0;
    doc["filtered_wt_g"]   = round(filtered_weight * 100.0) / 100.0;
    doc["rfid_tag"]        = current_rfid;
    doc["status"]          = mqttClient.connected() ? "ONLINE" : "BUFFERED";

    String jsonString;
    serializeJson(doc, jsonString);

    if (mqttClient.connected()) {
        if (mqttClient.publish(MQTT_TOPIC, jsonString.c_str())) {
            Serial.print("[PUBLISH SUCCESS] -> ");
            Serial.println(jsonString);
        } else {
            saveOfflinePayload(jsonString);
        }
    } else {
        saveOfflinePayload(jsonString);
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n--- STOCKSENSE ESP32 TELEMETRY NODE INIT ---");

    pinMode(LOAD_CELL_PIN, INPUT);
    connectWiFi();
    mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) {
        connectWiFi();
    }
    if (WiFi.status() == WL_CONNECTED && !mqttClient.connected()) {
        connectMQTT();
    }

    mqttClient.loop();

    if (millis() - last_pub_time >= PUB_INT) {
        last_pub_time = millis();
        publishTelemetry();
    }
}