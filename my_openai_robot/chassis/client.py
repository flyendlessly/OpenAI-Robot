"""Chassis serial client implementation for Raspberry Pi communicating with ESP32-S3."""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional, Union

from ..logger import get_logger
from .models import (
    AckResponse,
    ChassisActionResult,
    MotionCommand,
    PingCommand,
    StopCommand,
    TelemetryFrame,
)

logger = get_logger("chassis.client")


class ChassisController:
    """底盘硬件控制器：管理树莓派与 ESP32-S3 之间的串口长连接与命令帧调度。"""

    def __init__(
        self,
        port: str = "/dev/ttyACM0",
        baudrate: int = 115200,
        timeout: float = 1.0,
        max_speed: int = 70,
        max_duration_ms: int = 3000,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.max_speed = max_speed
        self.max_duration_ms = max_duration_ms

        self._seq = 1
        self._lock = threading.Lock()
        self._ser: Any = None
        self._running = False
        self._read_thread: Optional[threading.Thread] = None
        self._latest_telemetry: Optional[TelemetryFrame] = None
        self._pending_acks: Dict[int, AckResponse] = {}

    def connect(self) -> bool:
        """建立串口物理连接并启动后台监听线程"""
        try:
            import serial
        except ImportError:
            logger.error("pyserial 未安装，无法连接真实底盘串口。请执行: pip install pyserial")
            return False

        with self._lock:
            try:
                self._ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
                self._running = True
                self._read_thread = threading.Thread(target=self._reader_loop, daemon=True)
                self._read_thread.start()
                logger.info("成功连接 ESP32-S3 底盘串口: %s @ %d bps", self.port, self.baudrate)
                return True
            except Exception as e:
                logger.warning("打开底盘串口失败 (%s): %s", self.port, e)
                self._ser = None
                return False

    def close(self) -> None:
        """安全关闭连接并急停底盘"""
        self.stop()
        self._running = False
        with self._lock:
            if self._ser and self._ser.is_open:
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
        logger.info("底盘串口连接已关闭")

    @property
    def is_connected(self) -> bool:
        return bool(self._ser and self._ser.is_open and self._running)

    def _next_seq(self) -> int:
        seq = self._seq
        self._seq += 1
        return seq

    def _reader_loop(self) -> None:
        """后台轮询接收下位机 ACK 与遥测包"""
        while self._running and self._ser and self._ser.is_open:
            try:
                raw_bytes = self._ser.readline()
                if not raw_bytes:
                    continue
                line = raw_bytes.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("[底盘原始日志] %s", line)
                    continue

                msg_type = data.get("type")
                if msg_type == "telemetry":
                    self._latest_telemetry = TelemetryFrame(**data)
                elif msg_type == "ack":
                    ack = AckResponse(**data)
                    self._pending_acks[ack.seq] = ack
            except Exception as e:
                if self._running:
                    logger.debug("底盘串口接收遇到瞬态异常: %s", e)
                time.sleep(0.05)

    def _send_raw_line(self, line: str) -> bool:
        with self._lock:
            if not self._ser or not self._ser.is_open:
                logger.warning("底盘串口未连接，指令发送被跳过")
                return False
            try:
                self._ser.write(line.encode("utf-8"))
                self._ser.flush()
                return True
            except Exception as e:
                logger.error("底盘串口写入失败: %s", e)
                return False

    def ping(self) -> bool:
        """向下位机发送探活心跳"""
        seq = self._next_seq()
        cmd = PingCommand(seq=seq)
        return self._send_raw_line(cmd.to_line())

    def stop(self) -> ChassisActionResult:
        """立即下发急停刹车指令"""
        seq = self._next_seq()
        cmd = StopCommand(seq=seq)
        ok = self._send_raw_line(cmd.to_line())
        return ChassisActionResult(
            success=ok,
            action="stop",
            message="底盘已执行紧急刹车停止" if ok else "急停指令发送失败，串口未连通",
        )

    def execute_action(
        self,
        action: str,
        *,
        duration_ms: int = 1000,
        speed: int = 50,
    ) -> ChassisActionResult:
        """将高层语义动作翻译为左右轮差速运动指令并下发"""
        if action == "stop":
            return self.stop()

        # 防御性安全限制：速度与时长强制夹紧
        safe_speed = max(10, min(speed, self.max_speed))
        safe_duration = max(50, min(duration_ms, self.max_duration_ms))

        # 根据差速小车运动学计算左右轮目标速度
        if action == "forward":
            left_speed, right_speed = safe_speed, safe_speed
            desc = "向前行进"
        elif action == "backward":
            left_speed, right_speed = -safe_speed, -safe_speed
            desc = "向后退行"
        elif action == "turn_left":
            left_speed, right_speed = -safe_speed, safe_speed
            desc = "原地左转"
        elif action == "turn_right":
            left_speed, right_speed = safe_speed, -safe_speed
            desc = "原地右转"
        else:
            return ChassisActionResult(
                success=False,
                action=action,
                message=f"不支持的动作类型: {action}",
            )

        seq = self._next_seq()
        cmd = MotionCommand(
            seq=seq,
            left=left_speed,
            right=right_speed,
            time_ms=safe_duration,
        )

        ok = self._send_raw_line(cmd.to_line())
        if not ok:
            return ChassisActionResult(
                success=False,
                action=action,
                message=f"无法下发{desc}指令，请检查小车串口是否正确连接",
            )

        logger.info("已下发底盘动作 [%s]: seq=%d, left=%d, right=%d, time=%dms", action, seq, left_speed, right_speed, safe_duration)
        return ChassisActionResult(
            success=True,
            action=action,
            message=f"已成功控制小车{desc}，速度 {safe_speed}%，持续 {safe_duration} 毫秒",
            details={
                "seq": seq,
                "left": left_speed,
                "right": right_speed,
                "duration_ms": safe_duration,
            },
        )

    def get_telemetry(self) -> Optional[TelemetryFrame]:
        """获取下位机最新的遥测数据"""
        return self._latest_telemetry
