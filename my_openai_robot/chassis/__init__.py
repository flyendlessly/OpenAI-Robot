"""Robot Chassis controller subsystem package."""
from __future__ import annotations

from typing import Union

from ..config import ChassisSettings
from ..logger import get_logger
from .client import ChassisController
from .mock import MockChassisController
from .models import (
    AckResponse,
    ChassisActionResult,
    MotionCommand,
    PingCommand,
    StopCommand,
    TelemetryFrame,
)
from .tools import (
    CHASSIS_TOOL_DEFINITION,
    ChassisControllerProtocol,
    execute_chassis_tool,
)

logger = get_logger("chassis")

__all__ = [
    "ChassisController",
    "MockChassisController",
    "ChassisControllerProtocol",
    "MotionCommand",
    "StopCommand",
    "PingCommand",
    "AckResponse",
    "TelemetryFrame",
    "ChassisActionResult",
    "CHASSIS_TOOL_DEFINITION",
    "execute_chassis_tool",
    "create_chassis_controller",
]


def create_chassis_controller(
    settings: ChassisSettings,
) -> Union[ChassisController, MockChassisController]:
    """根据配置创建真实串口控制器或虚拟 Mock 控制器"""
    if settings.mock:
        logger.info("创建 Mock 虚拟底盘控制器 (调试模式)")
        controller = MockChassisController(
            max_speed=settings.max_speed,
            max_duration_ms=settings.max_duration_ms,
        )
        controller.connect()
        return controller

    logger.info("创建串口底盘控制器: port=%s, baudrate=%d", settings.port, settings.baudrate)
    real_controller = ChassisController(
        port=settings.port,
        baudrate=settings.baudrate,
        timeout=settings.timeout,
        max_speed=settings.max_speed,
        max_duration_ms=settings.max_duration_ms,
    )
    # 尝试连接，若失败且配置了允许降级或提示
    connected = real_controller.connect()
    if not connected:
        logger.warning(
            "未成功连通底盘物理串口 %s。若在开发机无硬件环境下调试，请设置 CHASSIS_MOCK=true",
            settings.port,
        )
    return real_controller
