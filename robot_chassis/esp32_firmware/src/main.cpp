/**
 * @file main.cpp
 * @brief ESP32-S3 面包板阶段最小验证固件
 *
 * 硬件说明：
 * - 左右轮各用一个普通 LED 模拟：
 *   - 左轮指示灯：GPIO 4 (串联 220Ω~1kΩ 电阻接地)
 *   - 右轮指示灯：GPIO 5 (串联 220Ω~1kΩ 电阻接地)
 * - 通信方式：USB CDC / UART0 串口（115200 波特率）
 *
 * 功能：
 * 1. 监听并解析 JSON 控制指令 (motion, stop, ping)
 * 2. 硬件看门狗超时保护：到达指定 time_ms 自动熄灯刹车并上报 motion_done
 * 3. 5Hz 周期性模拟遥测包上报
 */

#include <Arduino.h>
#include <ArduinoJson.h>

// 兼容 ArduinoJson v6 与 v7 内存模型
#if ARDUINOJSON_VERSION_MAJOR >= 7
    #define JSON_DOC(name, size) JsonDocument name
#else
    #define JSON_DOC(name, size) StaticJsonDocument<size> name
#endif

// 引脚定义 (可根据实际面包板接线修改)
constexpr int PIN_LEFT_LED  = 4;
constexpr int PIN_RIGHT_LED = 5;

// 状态机
enum State {
    STATE_READY,
    STATE_MOVING,
    STATE_ALARM
};

State currentState = STATE_READY;
unsigned long motionDeadline = 0;
unsigned long lastTelemetryTime = 0;
int lastSeq = 0;

void applyMotion(int leftSpeed, int rightSpeed) {
    // 面包板阶段：使用数字高低电平或简易亮度模拟车轮驱动
    digitalWrite(PIN_LEFT_LED, leftSpeed != 0 ? HIGH : LOW);
    digitalWrite(PIN_RIGHT_LED, rightSpeed != 0 ? HIGH : LOW);
}

void stopCar() {
    digitalWrite(PIN_LEFT_LED, LOW);
    digitalWrite(PIN_RIGHT_LED, LOW);
    currentState = STATE_READY;
}

void sendAck(int seq, const char* status, const char* msg = nullptr) {
    JSON_DOC(doc, 128);
    doc["type"] = "ack";
    doc["seq"] = seq;
    doc["status"] = status;
    if (msg) doc["msg"] = msg;
    serializeJson(doc, Serial);
    Serial.println();
}

void sendEvent(const char* eventName, int seq) {
    JSON_DOC(doc, 128);
    doc["type"] = "event";
    doc["event"] = eventName;
    doc["seq"] = seq;
    serializeJson(doc, Serial);
    Serial.println();
}

void sendTelemetry() {
    JSON_DOC(doc, 192);
    doc["type"] = "telemetry";
    doc["uptime_s"] = millis() / 1000;
    doc["v_batt"] = 8.12;       // 面包板阶段模拟满电 2S 电池 (8.12V)
    doc["dist_cm"] = 45.0;      // 模拟前方无障碍物
    doc["state"] = (currentState == STATE_MOVING) ? "MOVING" : "READY";
    serializeJson(doc, Serial);
    Serial.println();
}

void handleCommand(const String& line) {
    JSON_DOC(doc, 256);
    DeserializationError err = deserializeJson(doc, line);
    if (err) {
        sendAck(0, "error", "invalid_json");
        return;
    }

    const char* cmd = doc["cmd"] | "";
    int seq = doc["seq"] | 0;

    if (strcmp(cmd, "motion") == 0) {
        int left = doc["left"] | 0;
        int right = doc["right"] | 0;
        int timeMs = doc["time_ms"] | 1000;

        // 参数合法性边界约束
        if (timeMs < 50 || timeMs > 10000) {
            sendAck(seq, "error", "time_ms out of bounds [50, 10000]");
            return;
        }

        applyMotion(left, right);
        currentState = STATE_MOVING;
        motionDeadline = millis() + timeMs;
        lastSeq = seq;
        sendAck(seq, "ok");

    } else if (strcmp(cmd, "stop") == 0) {
        stopCar();
        sendAck(seq, "ok");

    } else if (strcmp(cmd, "ping") == 0) {
        sendAck(seq, "pong");

    } else {
        sendAck(seq, "error", "unknown_cmd");
    }
}

void setup() {
    Serial.begin(115200);
    pinMode(PIN_LEFT_LED, OUTPUT);
    pinMode(PIN_RIGHT_LED, OUTPUT);
    stopCar();
}

void loop() {
    // 1. 检查串口是否有完整的一行 JSON
    if (Serial.available() > 0) {
        String line = Serial.readStringUntil('\n');
        line.trim();
        if (line.length() > 0) {
            handleCommand(line);
        }
    }

    // 2. 防御性安全检查：超时自动刹车
    if (currentState == STATE_MOVING && millis() >= motionDeadline) {
        stopCar();
        sendEvent("motion_done", lastSeq);
    }

    // 3. 周期性上报遥测数据 (每 500ms 一次，避免刷屏)
    if (millis() - lastTelemetryTime >= 500) {
        lastTelemetryTime = millis();
        sendTelemetry();
    }
}
