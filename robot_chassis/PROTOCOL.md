# 树莓派与 ESP32-S3 串口通信协议规范 (Protocol Specification v1.0)

> **物理层规范**：
> - 传输介质：USB 虚拟串口 (CDC-ACM) 或 UART 硬件串口 (TX/RX 直连)
> - 波特率：`115200` bps
> - 数据位：`8` | 校验位：`None` | 停止位：`1` (8N1)
> - 封包规范：**JSON Lines (`ndjson`)**，每个数据包必须以换行符 `\n` 结尾，单包最大长度 256 字节。

---

## 1. 上位机 -> 下位机 (Commands)

### 1.1 运动控制帧 (`cmd: "motion"`)
控制小车按照指定的左右轮速度或直线移动。

```json
{
  "cmd": "motion",
  "seq": 101,
  "left": 50,
  "right": 50,
  "time_ms": 1000
}
```
* **字段说明**：
  * `cmd` (string): 固定为 `"motion"`。
  * `seq` (int): 请求序列号，下位机回包时原样带回，用于防重和应答对齐。
  * `left` (int): 左轮目标速度百分比，范围 `[-100, 100]`（正数前进，负数后退）。
  * `right` (int): 右轮目标速度百分比，范围 `[-100, 100]`。
  * `time_ms` (int): 最大持续时间 (毫秒)，范围 `[50, 10000]`。**超时后 ESP32-S3 必须自动停机**。

---

### 1.2 紧急停止帧 (`cmd: "stop"`)
不管当前处于什么动作，立即刹车并复位定时器。

```json
{
  "cmd": "stop",
  "seq": 102
}
```

---

### 1.3 心跳/探活帧 (`cmd: "ping"`)

```json
{
  "cmd": "ping",
  "seq": 103
}
```

---

## 2. 下位机 -> 上位机 (Responses & Telemetry)

### 2.1 指令即时确认帧 (`type: "ack"`)
收到上位机合法指令后立即回复。

```json
{
  "type": "ack",
  "seq": 101,
  "status": "ok"
}
```
* 如果指令参数超限或非法：
```json
{
  "type": "ack",
  "seq": 101,
  "status": "error",
  "msg": "speed out of range"
}
```

---

### 2.2 动作完成通知帧 (`type: "event"`)
当一次带时间的运动执行完毕或被中断时主动上报。

```json
{
  "type": "event",
  "event": "motion_done",
  "seq": 101
}
```
* 如果是因为障碍物触发制动：
```json
{
  "type": "event",
  "event": "obstacle_abort",
  "dist_cm": 12.5
}
```

---

### 2.3 周期性遥测帧 (`type: "telemetry"`)
ESP32-S3 以固定频率（建议 5Hz，即每 200ms 一次）上报。

```json
{
  "type": "telemetry",
  "uptime_s": 128,
  "v_batt": 8.12,
  "dist_cm": 45.0,
  "left_rpm": 0,
  "right_rpm": 0,
  "state": "READY"
}
```
* **字段说明**：
  * `uptime_s` (int): 下位机开机运行秒数。
  * `v_batt` (float): 当前动力电池电压（便于上位机评估是否需要提示充电）。
  * `dist_cm` (float): 前向测距传感器读数（厘米）。
  * `state` (string): `"READY"` / `"MOVING"` / `"ALARM"`。
