"""Mock Chassis implementation for local debugging without physical hardware."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from ..logger import get_logger
from .models import AckResponse, ChassisActionResult, TelemetryFrame

logger = get_logger("chassis.mock")


class MockChassisController:
    """虚拟小车底盘控制器：在无硬件或开发测试时模拟动作与遥测。"""

    def __init__(self, max_speed: int = 70, max_duration_ms: int = 3000) -> None:
        self.max_speed = max_speed
        self.max_duration_ms = max_duration_ms
        self.is_connected = True
        self.current_state = "idle"
        self._lock = threading.Lock()
        self.simulated_battery_v = 7.4
        self.simulated_dist_cm = 120.0
        logger.info(
            "MockChassisController initialized: max_speed=%d%%, max_duration=%dms",
            max_speed,
            max_duration_ms,
        )

    def connect(self) -> bool:
        self.is_connected = True
        logger.info("[Mock 底盘] 虚拟连接建立成功")
        return True

    def close(self) -> None:
        self.is_connected = False
        logger.info("[Mock 底盘] 虚拟连接已关闭")

    def ping(self) -> bool:
        logger.info("[Mock 底盘] Ping 探活响应: OK")
        return True

    def execute_action(
        self,
        action: str,
        *,
        duration_ms: int = 1000,
        speed: int = 50,
    ) -> ChassisActionResult:
        """执行上层抽象动作（前进、后退、左转、右转、停止）"""
        with self._lock:
            # 防御性截断
            safe_speed = max(10, min(speed, self.max_speed))
            safe_duration = max(50, min(duration_ms, self.max_duration_ms))

            if action == "stop":
                self.current_state = "idle"
                logger.info("[Mock 底盘] 🛑 紧急停止")
                return ChassisActionResult(
                    success=True,
                    action="stop",
                    message="底盘已立即刹车停止",
                )

            action_desc = {
                "forward": f"向前直线行进 (速度={safe_speed}%, 持续={safe_duration}ms)",
                "backward": f"向后倒车退行 (速度={safe_speed}%, 持续={safe_duration}ms)",
                "turn_left": f"原地向左旋转 (速度={safe_speed}%, 持续={safe_duration}ms)",
                "turn_right": f"原地向右旋转 (速度={safe_speed}%, 持续={safe_duration}ms)",
            }.get(action, f"执行自定义动作 {action}")

            logger.info("[Mock 底盘] 🚗 动作执行: %s", action_desc)
            self.current_state = "moving"
            # 模拟执行延迟（不阻塞过久，仅微量示意）
            time.sleep(0.05)
            self.current_state = "idle"

            return ChassisActionResult(
                success=True,
                action=action,
                message=f"已成功完成{action_desc}",
                details={
                    "speed": safe_speed,
                    "duration_ms": safe_duration,
                    "mock": True,
                },
            )

    def get_telemetry(self) -> TelemetryFrame:
        """获取当前遥测状态"""
        return TelemetryFrame(
            type="telemetry",
            status="ok",
            state=self.current_state,
            v_batt=self.simulated_battery_v,
            battery_mv=int(self.simulated_battery_v * 1000),
            dist_cm=self.simulated_dist_cm,
            dist_front_cm=int(self.simulated_dist_cm),
        )
