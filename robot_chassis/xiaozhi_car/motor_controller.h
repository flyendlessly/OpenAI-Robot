/**
 * @file motor_controller.h
 * @brief ESP32-S3 4WD 小车底层电机驱动 (基于 ESP-IDF 硬件定时器与 GPIO)
 */

#ifndef MOTOR_CONTROLLER_H
#define MOTOR_CONTROLLER_H

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// ==================== 默认引脚配置 (可根据实际连线修改) ====================
// 推荐使用不与 PSRAM (GPIO 35~37) 及常见 I2S 音频冲突的引脚
#define DEFAULT_PIN_LEFT_IN1    1   // 左轮电机方向引脚 1
#define DEFAULT_PIN_LEFT_IN2    2   // 左轮电机方向引脚 2
#define DEFAULT_PIN_RIGHT_IN1   41  // 右轮电机方向引脚 1
#define DEFAULT_PIN_RIGHT_IN2   42  // 右轮电机方向引脚 2

/**
 * @brief 动作枚举定义
 */
typedef enum {
    CHASSIS_ACTION_STOP = 0,
    CHASSIS_ACTION_FORWARD,
    CHASSIS_ACTION_BACKWARD,
    CHASSIS_ACTION_TURN_LEFT,
    CHASSIS_ACTION_TURN_RIGHT,
    CHASSIS_ACTION_DANCE        // 趣味动作：小车原地摇摆扭屁股
} chassis_action_t;

/**
 * @brief 初始化电机 GPIO 与安全防撞定时器
 * @return esp_err_t ESP_OK 表示初始化成功
 */
esp_err_t motor_init(void);

/**
 * @brief 执行底盘动作
 * @param action 动作类型 (前进/后退/左转/右转/急停/跳舞)
 * @param duration_ms 持续运行时间(毫秒)，超时后由硬件定时器自动刹车
 * @return esp_err_t
 */
esp_err_t motor_do_action(chassis_action_t action, uint32_t duration_ms);

/**
 * @brief 紧急物理制动刹车 (立即熄灭所有驱动)
 */
void motor_stop(void);

#ifdef __cplusplus
}
#endif

#endif // MOTOR_CONTROLLER_H
