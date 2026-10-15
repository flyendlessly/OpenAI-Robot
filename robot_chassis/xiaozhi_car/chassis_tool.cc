/**
 * @file chassis_tool.cc
 * @brief 小智 AI (XiaoZhi) 大模型 Function Calling / Tool 桥接模块
 */

#include "motor_controller.h"
#include <string>
#include <cstring>
#include "esp_log.h"
#include "cJSON.h"

static const char *TAG = "ChassisTool";

/**
 * 1. 提供给大模型 Function Calling 的 Tool Schema (声明小车的运动技能)
 */
const char* CHASSIS_TOOL_SCHEMA = R"({
    "name": "control_chassis",
    "description": "控制智能 4WD 小车底盘的运动姿态，如前进、后退、转弯、刹车或开心跳舞",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["forward", "backward", "turn_left", "turn_right", "stop", "dance"],
                "description": "移动动作: forward(前进), backward(后退), turn_left(左转), turn_right(右转), stop(停下), dance(开心摇摆跳舞)"
            },
            "duration_ms": {
                "type": "integer",
                "description": "动作持续时间(毫秒)，默认 1000ms，范围 200~5000"
            }
        },
        "required": ["action"]
    }
})";

/**
 * 2. 大模型触发 Tool Call 时的执行回调函数
 * @param json_args 大模型下发的 JSON 参数字符串，例如 {"action": "forward", "duration_ms": 1000}
 * @return 返回给大模型的确认文本（大模型会基于此回复语音反馈给人类）
 */
extern "C" std::string execute_chassis_tool(const char* json_args) {
    ESP_LOGI(TAG, "收到大模型下发底盘指令: %s", json_args ? json_args : "null");

    if (!json_args) {
        return "{\"success\": false, \"message\": \"缺少指令参数\"}";
    }

    cJSON *root = cJSON_Parse(json_args);
    if (!root) {
        return "{\"success\": false, \"message\": \"JSON 参数解析失败\"}";
    }

    cJSON *action_item = cJSON_GetObjectItem(root, "action");
    cJSON *duration_item = cJSON_GetObjectItem(root, "duration_ms");

    if (!action_item || !cJSON_IsString(action_item)) {
        cJSON_Delete(root);
        return "{\"success\": false, \"message\": \"缺少有效的 action 字段\"}";
    }

    const char* action_str = action_item->valuestring;
    uint32_t duration_ms = 1000;
    if (duration_item && cJSON_IsNumber(duration_item)) {
        duration_ms = (uint32_t)duration_item->valueint;
    }

    chassis_action_t act = CHASSIS_ACTION_STOP;
    std::string reply_msg = "已执行";

    if (strcmp(action_str, "forward") == 0) {
        act = CHASSIS_ACTION_FORWARD;
        reply_msg = "小车正在向前开动";
    } else if (strcmp(action_str, "backward") == 0) {
        act = CHASSIS_ACTION_BACKWARD;
        reply_msg = "小车正在缓缓倒车";
    } else if (strcmp(action_str, "turn_left") == 0) {
        act = CHASSIS_ACTION_TURN_LEFT;
        reply_msg = "小车正在向左转弯";
    } else if (strcmp(action_str, "turn_right") == 0) {
        act = CHASSIS_ACTION_TURN_RIGHT;
        reply_msg = "小车正在向右转弯";
    } else if (strcmp(action_str, "dance") == 0) {
        act = CHASSIS_ACTION_DANCE;
        reply_msg = "小车开心得扭屁股跳舞啦！";
    } else {
        act = CHASSIS_ACTION_STOP;
        reply_msg = "小车已平稳停下";
    }

    motor_do_action(act, duration_ms);
    cJSON_Delete(root);

    return std::string("{\"success\": true, \"message\": \"") + reply_msg + "\"}";
}
