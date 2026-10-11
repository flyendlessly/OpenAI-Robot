#!/usr/bin/env python3
"""
虚拟底盘模拟器 (Mock Chassis Simulator)
模拟 ESP32-S3 下位机的行为，包含：
1. JSON 协议解析与校验
2. 动作定时器与 motion_done 事件触发
3. 周期性遥测上报 (5Hz)

可用于上层应用在无硬件环境下的集成与自动化测试。
"""

import json
import time
import threading


class MockChassis:
    def __init__(self):
        self.state = "READY"
        self.uptime_start = time.time()
        self.last_seq = 0
        self.motion_timer = None
        self.running = True

    def process_command(self, line: str) -> list[str]:
        """处理输入的命令行，返回下位机生成的响应行列表"""
        responses = []
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            return [json.dumps({"type": "ack", "seq": 0, "status": "error", "msg": "invalid_json"})]

        cmd = doc.get("cmd")
        seq = doc.get("seq", 0)

        if cmd == "motion":
            time_ms = doc.get("time_ms", 1000)
            if time_ms < 50 or time_ms > 10000:
                responses.append(json.dumps({"type": "ack", "seq": seq, "status": "error", "msg": "time_ms out of bounds"}))
                return responses

            self.state = "MOVING"
            self.last_seq = seq
            responses.append(json.dumps({"type": "ack", "seq": seq, "status": "ok"}))

            # 模拟超时自动刹车
            if self.motion_timer and self.motion_timer.is_alive():
                self.motion_timer.cancel()
            self.motion_timer = threading.Timer(time_ms / 1000.0, self._on_motion_done, args=[seq])
            self.motion_timer.start()

        elif cmd == "stop":
            if self.motion_timer and self.motion_timer.is_alive():
                self.motion_timer.cancel()
            self.state = "READY"
            responses.append(json.dumps({"type": "ack", "seq": seq, "status": "ok"}))

        elif cmd == "ping":
            responses.append(json.dumps({"type": "ack", "seq": seq, "status": "pong"}))

        else:
            responses.append(json.dumps({"type": "ack", "seq": seq, "status": "error", "msg": "unknown_cmd"}))

        return responses

    def _on_motion_done(self, seq: int):
        self.state = "READY"
        event = json.dumps({"type": "event", "event": "motion_done", "seq": seq})
        print(f"\n[Mock 事件触发] {event}")

    def get_telemetry(self) -> str:
        return json.dumps({
            "type": "telemetry",
            "uptime_s": int(time.time() - self.uptime_start),
            "v_batt": 8.05,
            "dist_cm": 42.5,
            "state": self.state
        })


if __name__ == "__main__":
    chassis = MockChassis()
    print("=== 虚拟底盘模拟器已启动 ===")
    print("请输入 JSON 指令进行测试 (例如: {\"cmd\":\"motion\",\"seq\":1,\"left\":50,\"right\":50,\"time_ms\":1000})")
    try:
        while True:
            cmd_line = input("> ").strip()
            if not cmd_line:
                continue
            resps = chassis.process_command(cmd_line)
            for r in resps:
                print(f"[回复] {r}")
    except KeyboardInterrupt:
        print("\n模拟器退出。")
