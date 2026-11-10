"""OpenAI Function / Tool Calling definitions and execution router for Chassis."""
from __future__ import annotations

import json
from typing import Any, Dict, Protocol, Union

from ..logger import get_logger
from .models import ChassisActionResult

logger = get_logger("chassis.tools")

CHASSIS_TOOL_DEFINITION: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "control_chassis",
        "description": (
            "控制移动机器人小车底盘的运动与行走，包括前进、倒退、向左转、向右转与紧急停止刹车。"
            "当用户发出包含移动、走动、转弯、退后、转圈或停止动作的语音指令时调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["forward", "backward", "turn_left", "turn_right", "stop"],
                    "description": (
                        "动作类型：forward(前进)、backward(倒退)、"
                        "turn_left(向左原地转弯)、turn_right(向右原地转弯)、stop(紧急刹车停止)"
                    ),
                },
                "duration_ms": {
                    "type": "integer",
                    "description": "动作持续时间，单位毫秒。建议范围 300~3000ms，默认为 1000ms",
                    "default": 1000,
                },
                "speed": {
                    "type": "integer",
                    "description": "运动速度百分比，范围 10~70，默认 50",
                    "default": 50,
                },
            },
            "required": ["action"],
        },
    },
}


class ChassisControllerProtocol(Protocol):
    """底盘控制器协议规范"""

    def execute_action(
        self,
        action: str,
        *,
        duration_ms: int = 1000,
        speed: int = 50,
    ) -> ChassisActionResult:
        ...

    def stop(self) -> ChassisActionResult:
        ...


def execute_chassis_tool(
    controller: ChassisControllerProtocol,
    arguments_json: str,
) -> str:
    """解析大模型传入的 Tool Arguments JSON 并调度底盘控制器执行动作"""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except Exception as e:
        logger.error("解析 control_chassis 工具参数失败: %s, 原始数据: %s", e, arguments_json)
        return json.dumps({
            "success": False,
            "error": f"参数解析错误: {e}",
        }, ensure_ascii=False)

    action = args.get("action", "")
    duration_ms = args.get("duration_ms", 1000)
    speed = args.get("speed", 50)

    try:
        duration_ms = int(duration_ms)
    except (ValueError, TypeError):
        duration_ms = 1000

    try:
        speed = int(speed)
    except (ValueError, TypeError):
        speed = 50

    logger.info("执行底盘控制工具调用: action=%s, duration_ms=%d, speed=%d", action, duration_ms, speed)

    result = controller.execute_action(
        action=action,
        duration_ms=duration_ms,
        speed=speed,
    )

    return json.dumps({
        "success": result.success,
        "action": result.action,
        "message": result.message,
        "details": result.details,
    }, ensure_ascii=False)
