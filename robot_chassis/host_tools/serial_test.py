#!/usr/bin/env python3
"""
小车底盘独立串口调测终端 (Chassis Serial Test CLI)
完全独立于主工程，用于验证 ESP32-S3 通信协议、电机/LED 响应和超时机制。

使用方式:
    python serial_test.py [COM口或/dev/ttyUSB0]
例如:
    python serial_test.py COM3
"""

import sys
import json
import time
import threading
try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("错误: 未检测到 pyserial 库。请先安装: pip install pyserial")
    sys.exit(1)


class ChassisTester:
    def __init__(self, port: str, baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = serial.Serial(port, baudrate, timeout=1.0)
        self.running = True
        self.seq = 1

        # 启动后台读取线程
        self.read_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.read_thread.start()

    def _reader_loop(self):
        while self.running:
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    msg_type = data.get("type", "unknown")
                    if msg_type == "telemetry":
                        # 遥测包单行刷新显示，避免刷屏
                        print(f"\r[遥测] 状态:{data.get('state')} | 电压:{data.get('v_batt')}V | 距离:{data.get('dist_cm')}cm", end="", flush=True)
                    elif msg_type == "ack":
                        print(f"\n[ACK 应答] seq={data.get('seq')}, 状态={data.get('status')}")
                    elif msg_type == "event":
                        print(f"\n[EVENT 事件] 事件={data.get('event')}, seq={data.get('seq')}")
                    else:
                        print(f"\n[收到未分类数据] {line}")
                except json.JSONDecodeError:
                    print(f"\n[原始文本/调试] {line}")
            except Exception as e:
                if self.running:
                    print(f"\n[读取异常] {e}")
                break

    def send_cmd(self, payload: dict):
        payload["seq"] = self.seq
        self.seq += 1
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        self.ser.write(raw)
        self.ser.flush()

    def move(self, left: int, right: int, time_ms: int = 1000):
        self.send_cmd({
            "cmd": "motion",
            "left": left,
            "right": right,
            "time_ms": time_ms
        })

    def stop(self):
        self.send_cmd({"cmd": "stop"})

    def ping(self):
        self.send_cmd({"cmd": "ping"})

    def close(self):
        self.running = False
        self.ser.close()


def main():
    if len(sys.argv) > 1:
        target_port = sys.argv[1]
    else:
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            print("未检测到可用串口，请连接 ESP32-S3 后重试。")
            return
        print("发现以下可用串口:")
        for i, p in enumerate(ports):
            print(f"  [{i}] {p.device} - {p.description}")
        choice = input("请选择序号 (默认 0): ").strip()
        idx = int(choice) if choice.isdigit() else 0
        target_port = ports[idx].device

    print(f"\n正在连接 {target_port} @ 115200 ...")
    try:
        tester = ChassisTester(target_port)
    except Exception as e:
        print(f"打开串口失败: {e}")
        return

    print("\n" + "=" * 50)
    print("ESP32-S3 小车独立调测终端已就绪！")
    print("操作指令:")
    print("  [w] 前进 (左右各 50%, 持续 1000ms)")
    print("  [s] 后退 (左右各 -50%, 持续 1000ms)")
    print("  [a] 左转 (左-50%, 右50%, 持续 500ms)")
    print("  [d] 右转 (左50%, 右-50%, 持续 500ms)")
    print("  [空格] 紧急停止")
    print("  [p] 发送 Ping 心跳")
    print("  [q] 退出")
    print("=" * 50 + "\n")

    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "w":
                tester.move(50, 50, 1000)
            elif cmd == "s":
                tester.move(-50, -50, 1000)
            elif cmd == "a":
                tester.move(-50, 50, 500)
            elif cmd == "d":
                tester.move(50, -50, 500)
            elif cmd == "" or cmd == " ":
                tester.stop()
            elif cmd == "p":
                tester.ping()
            elif cmd == "q":
                break
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        tester.stop()
        tester.close()
        print("\n已安全退出。")


if __name__ == "__main__":
    main()
