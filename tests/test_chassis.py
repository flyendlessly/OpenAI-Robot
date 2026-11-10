"""Unit tests for Chassis subsystem and tool execution using unittest."""
import json
import unittest

from my_openai_robot.chassis import (
    CHASSIS_TOOL_DEFINITION,
    AckResponse,
    ChassisController,
    MockChassisController,
    MotionCommand,
    PingCommand,
    StopCommand,
    TelemetryFrame,
    create_chassis_controller,
    execute_chassis_tool,
)
from my_openai_robot.config import ChassisSettings


class TestChassisSubsystem(unittest.TestCase):
    def test_protocol_models_serialization(self):
        # 1. 运动指令帧测试
        motion = MotionCommand(seq=101, left=50, right=50, time_ms=1000)
        line = motion.to_line()
        self.assertTrue(line.endswith("\n"))
        data = json.loads(line)
        self.assertEqual(data["cmd"], "motion")
        self.assertEqual(data["seq"], 101)
        self.assertEqual(data["left"], 50)
        self.assertEqual(data["right"], 50)
        self.assertEqual(data["time_ms"], 1000)

        # 2. 急停帧测试
        stop = StopCommand(seq=102)
        stop_data = json.loads(stop.to_line())
        self.assertEqual(stop_data["cmd"], "stop")
        self.assertEqual(stop_data["seq"], 102)

        # 3. 探活心跳帧测试
        ping = PingCommand(seq=103)
        ping_data = json.loads(ping.to_line())
        self.assertEqual(ping_data["cmd"], "ping")

        # 4. ACK 响应测试
        ack = AckResponse(seq=101, status="ok")
        self.assertEqual(ack.status, "ok")
        self.assertEqual(ack.err_code, 0)

        # 5. 遥测帧测试
        telemetry = TelemetryFrame(
            seq=101,
            state="idle",
            v_batt=7.4,
            dist_cm=100.0,
        )
        self.assertEqual(telemetry.v_batt, 7.4)
        self.assertEqual(telemetry.dist_cm, 100.0)

    def test_mock_chassis_actions_and_safety_limits(self):
        controller = MockChassisController(max_speed=60, max_duration_ms=2000)
        self.assertTrue(controller.connect())
        self.assertTrue(controller.ping())

        # 1. 前进（正常参数）
        res = controller.execute_action("forward", duration_ms=1000, speed=50)
        self.assertTrue(res.success)
        self.assertEqual(res.action, "forward")
        self.assertEqual(res.details["speed"], 50)
        self.assertEqual(res.details["duration_ms"], 1000)

        # 2. 防御性安全限制测试（速度超标被夹紧为 60%，时间超标被截断为 2000ms）
        res_clamped = controller.execute_action("backward", duration_ms=5000, speed=99)
        self.assertTrue(res_clamped.success)
        self.assertEqual(res_clamped.details["speed"], 60)
        self.assertEqual(res_clamped.details["duration_ms"], 2000)

        # 3. 转向与急停
        res_left = controller.execute_action("turn_left", duration_ms=500, speed=40)
        self.assertTrue(res_left.success)

        res_stop = controller.execute_action("stop")
        self.assertTrue(res_stop.success)
        self.assertEqual(res_stop.action, "stop")

        # 4. 遥测读取
        telem = controller.get_telemetry()
        self.assertEqual(telem.v_batt, 7.4)
        self.assertEqual(telem.state, "idle")

        controller.close()
        self.assertFalse(controller.is_connected)

    def test_execute_chassis_tool(self):
        controller = MockChassisController()

        # 模拟 LLM 传入的 JSON 参数
        args_json = json.dumps({
            "action": "forward",
            "duration_ms": 1500,
            "speed": 40,
        })

        res_str = execute_chassis_tool(controller, args_json)
        res = json.loads(res_str)
        self.assertTrue(res["success"])
        self.assertEqual(res["action"], "forward")
        self.assertIn("成功", res["message"])

        # 异常输入测试（传入损坏的 json）
        corrupt_res_str = execute_chassis_tool(controller, "{invalid_json")
        corrupt_res = json.loads(corrupt_res_str)
        self.assertFalse(corrupt_res["success"])
        self.assertIn("错误", corrupt_res["error"])

    def test_chassis_factory_mock(self):
        settings = ChassisSettings(
            enabled=True,
            mock=True,
            max_speed=65,
            max_duration_ms=2500,
        )
        controller = create_chassis_controller(settings)
        self.assertIsInstance(controller, MockChassisController)
        self.assertEqual(controller.max_speed, 65)
        self.assertEqual(controller.max_duration_ms, 2500)
        self.assertTrue(controller.is_connected)


if __name__ == "__main__":
    unittest.main()
