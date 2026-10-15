/**
 * @file motor_controller.c
 * @brief ESP32-S3 4WD 小车电机驱动实现 (纯标准 ESP-IDF API)
 */

#include "motor_controller.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "MotorController";

static esp_timer_handle_t s_stop_timer = NULL;
static TaskHandle_t s_dance_task_handle = NULL;

static void set_left_motor(int forward) {
    if (forward > 0) {
        gpio_set_level(DEFAULT_PIN_LEFT_IN1, 1);
        gpio_set_level(DEFAULT_PIN_LEFT_IN2, 0);
    } else if (forward < 0) {
        gpio_set_level(DEFAULT_PIN_LEFT_IN1, 0);
        gpio_set_level(DEFAULT_PIN_LEFT_IN2, 1);
    } else {
        gpio_set_level(DEFAULT_PIN_LEFT_IN1, 0);
        gpio_set_level(DEFAULT_PIN_LEFT_IN2, 0);
    }
}

static void set_right_motor(int forward) {
    if (forward > 0) {
        gpio_set_level(DEFAULT_PIN_RIGHT_IN1, 1);
        gpio_set_level(DEFAULT_PIN_RIGHT_IN2, 0);
    } else if (forward < 0) {
        gpio_set_level(DEFAULT_PIN_RIGHT_IN1, 0);
        gpio_set_level(DEFAULT_PIN_RIGHT_IN2, 1);
    } else {
        gpio_set_level(DEFAULT_PIN_RIGHT_IN1, 0);
        gpio_set_level(DEFAULT_PIN_RIGHT_IN2, 0);
    }
}

static void timer_stop_callback(void* arg) {
    motor_stop();
    ESP_LOGI(TAG, "安全定时器触发: 小车自主平稳制动停机");
}

void motor_stop(void) {
    if (s_dance_task_handle != NULL) {
        vTaskDelete(s_dance_task_handle);
        s_dance_task_handle = NULL;
    }
    set_left_motor(0);
    set_right_motor(0);
}

static void dance_task(void *pvParameters) {
    uint32_t total_ms = (uint32_t)(uintptr_t)pvParameters;
    int step = 0;
    int max_steps = total_ms / 250;
    if (max_steps < 2) max_steps = 4;

    while (step < max_steps) {
        if (step % 2 == 0) {
            set_left_motor(1);
            set_right_motor(-1); // 原地左摆
        } else {
            set_left_motor(-1);
            set_right_motor(1);  // 原地右摆
        }
        vTaskDelay(pdMS_TO_TICKS(250));
        step++;
    }

    motor_stop();
    s_dance_task_handle = NULL;
    vTaskDelete(NULL);
}

esp_err_t motor_init(void) {
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << DEFAULT_PIN_LEFT_IN1) |
                        (1ULL << DEFAULT_PIN_LEFT_IN2) |
                        (1ULL << DEFAULT_PIN_RIGHT_IN1) |
                        (1ULL << DEFAULT_PIN_RIGHT_IN2),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_ENABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    esp_err_t err = gpio_config(&io_conf);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "GPIO 配置失败: %d", err);
        return err;
    }

    motor_stop();

    // 创建安全自动刹车定时器 (单次触发)
    const esp_timer_create_args_t timer_args = {
        .callback = &timer_stop_callback,
        .name = "chassis_watchdog"
    };
    err = esp_timer_create(&timer_args, &s_stop_timer);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "定时器创建失败: %d", err);
        return err;
    }

    ESP_LOGI(TAG, "4WD 小车电机驱动与安全看门狗初始化完成！(Pins: %d, %d, %d, %d)",
             DEFAULT_PIN_LEFT_IN1, DEFAULT_PIN_LEFT_IN2,
             DEFAULT_PIN_RIGHT_IN1, DEFAULT_PIN_RIGHT_IN2);
    return ESP_OK;
}

esp_err_t motor_do_action(chassis_action_t action, uint32_t duration_ms) {
    // 限制单次动作执行时间最大为 10 秒，防御死循环跑飞
    if (duration_ms == 0) duration_ms = 1000;
    if (duration_ms > 10000) duration_ms = 10000;

    // 先停止已有定时器和任务
    if (esp_timer_is_active(s_stop_timer)) {
        esp_timer_stop(s_stop_timer);
    }
    if (s_dance_task_handle != NULL) {
        vTaskDelete(s_dance_task_handle);
        s_dance_task_handle = NULL;
    }

    switch (action) {
        case CHASSIS_ACTION_FORWARD:
            set_left_motor(1);
            set_right_motor(1);
            break;
        case CHASSIS_ACTION_BACKWARD:
            set_left_motor(-1);
            set_right_motor(-1);
            break;
        case CHASSIS_ACTION_TURN_LEFT:
            set_left_motor(-1);
            set_right_motor(1);
            break;
        case CHASSIS_ACTION_TURN_RIGHT:
            set_left_motor(1);
            set_right_motor(-1);
            break;
        case CHASSIS_ACTION_STOP:
            motor_stop();
            return ESP_OK;
        case CHASSIS_ACTION_DANCE:
            xTaskCreate(dance_task, "dance_task", 2048, (void*)(uintptr_t)duration_ms, 5, &s_dance_task_handle);
            return ESP_OK;
        default:
            motor_stop();
            return ESP_ERR_INVALID_ARG;
    }

    // 启动安全看门狗定时器 (微秒计算)
    esp_timer_start_once(s_stop_timer, (uint64_t)duration_ms * 1000ULL);
    ESP_LOGI(TAG, "底盘动作开始: action=%d, 持续时间=%lu ms", action, duration_ms);
    return ESP_OK;
}
