"""Chassis protocol data models and schemas based on robot_chassis/PROTOCOL.md."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field


class MotionCommand(BaseModel):
    """运动控制指令帧 (上位机 -> 下位机)"""
    cmd: Literal["motion"] = "motion"
    seq: int = Field(default=1, description="请求序列号，递增")
    left: int = Field(..., ge=-100, le=100, description="左轮速度百分比 [-100, 100]")
    right: int = Field(..., ge=-100, le=100, description="右轮速度百分比 [-100, 100]")
    time_ms: int = Field(default=1000, ge=50, le=10000, description="持续执行时间 (毫秒)")

    def to_line(self) -> str:
        """序列化为 JSON Lines 协议帧"""
        return self.model_dump_json() + "\n"


class StopCommand(BaseModel):
    """紧急停止指令帧 (上位机 -> 下位机)"""
    cmd: Literal["stop"] = "stop"
    seq: int = Field(default=1, description="请求序列号")

    def to_line(self) -> str:
        return self.model_dump_json() + "\n"


class PingCommand(BaseModel):
    """心跳/探活指令帧 (上位机 -> 下位机)"""
    cmd: Literal["ping"] = "ping"
    seq: int = Field(default=1, description="请求序列号")

    def to_line(self) -> str:
        return self.model_dump_json() + "\n"


class AckResponse(BaseModel):
    """指令确认帧 (下位机 -> 上位机)"""
    type: Literal["ack"] = "ack"
    seq: int
    status: Literal["ok", "err"] = "ok"
    err_code: int = 0
    msg: Optional[str] = None


class TelemetryFrame(BaseModel):
    """遥测广播与状态帧 (下位机 -> 上位机)"""
    type: Literal["telemetry"] = "telemetry"
    seq: Optional[int] = None
    status: Optional[str] = None
    state: Optional[str] = None
    battery_mv: Optional[int] = None
    v_batt: Optional[float] = None
    dist_front_cm: Optional[int] = None
    dist_cm: Optional[float] = None


class ChassisActionResult(BaseModel):
    """上层动作执行统一结果，用于供大模型总结反馈"""
    success: bool
    action: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
