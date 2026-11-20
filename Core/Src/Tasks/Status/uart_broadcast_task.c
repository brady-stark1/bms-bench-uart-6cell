#include "Tasks/Status/uart_broadcast_task.h"

#include <stdarg.h>
#include <stdio.h>

static TaskHandle_t volatile tx_waiter;
static char report[UART_BROADCAST_BUFFER_BYTES];
static size_t report_length;
static ams_measurement_t snapshot;

static void append(const char *format, ...)
{
    const size_t capacity = sizeof(report) - report_length;
    va_list args;
    int written;

    if (capacity <= 1U) {
        return;
    }
    va_start(args, format);
    written = vsnprintf(&report[report_length], capacity, format, args);
    va_end(args);
    if (written < 0) {
        return;
    }
    /* On overflow keep the truncated text; later appends are dropped. */
    report_length += ((size_t)written < capacity) ? (size_t)written :
        capacity - 1U;
}

/* Prints a milli-unit value as a signed decimal without printf float
 * support, which newlib-nano omits by default. */
static void append_milli(const char *label, uint16_t index, int32_t milli,
    const char *unit)
{
    const uint32_t magnitude = (milli < 0) ?
        (uint32_t)(-(int64_t)milli) : (uint32_t)milli;
    const char *sign = (milli < 0) ? "-" : "";

    if (index != 0U) {
        append("%s[%u]=%s%lu.%03lu %s\r\n", label, (unsigned)index, sign,
            (unsigned long)(magnitude / 1000U),
            (unsigned long)(magnitude % 1000U), unit);
    } else {
        append("%s=%s%lu.%03lu %s\r\n", label, sign,
            (unsigned long)(magnitude / 1000U),
            (unsigned long)(magnitude % 1000U), unit);
    }
}

static void take_snapshot(const app_data_t *data)
{
    taskENTER_CRITICAL();
    snapshot = data->last_measurement;
    taskEXIT_CRITICAL();
}

static void build_report(void)
{
    uint16_t index;

    report_length = 0U;
    for (index = 0U; index < UART_BROADCAST_CELL_COUNT; index++) {
        if (snapshot.status == AMS_SAMPLE_VALID &&
            index < snapshot.valid_cell_count && index < AMS_MAX_CELLS) {
            append_milli("cell", (uint16_t)(index + 1U),
                snapshot.cell_voltage_mv[index], "V");
        } else {
            append("cell[%u]=N/A\r\n", (unsigned)(index + 1U));
        }
    }
}

static void transmit_report(void)
{
    if (report_length == 0U) {
        return;
    }
    (void)ulTaskNotifyTake(pdTRUE, 0U);
    tx_waiter = xTaskGetCurrentTaskHandle();
    if (HAL_UART_Transmit_IT(&huart1, (const uint8_t *)report,
        (uint16_t)report_length) != HAL_OK) {
        tx_waiter = NULL;
        return;
    }
    /* The buffer must stay untouched until the interrupt-driven transfer
     * finishes, so wait for it (or abort) before building the next one. */
    if (ulTaskNotifyTake(pdTRUE,
        pdMS_TO_TICKS(UART_BROADCAST_TX_TIMEOUT_MS)) == 0U) {
        (void)HAL_UART_AbortTransmit(&huart1);
    }
    tx_waiter = NULL;
}

void uart_broadcast_task(void *argument)
{
    const app_data_t *data = (const app_data_t *)argument;
    TickType_t last_wake = xTaskGetTickCount();

    for (;;) {
        take_snapshot(data);
        build_report();
        transmit_report();
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(UART_BROADCAST_PERIOD_MS));
    }
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    BaseType_t woken = pdFALSE;

    if (huart == &huart1 && tx_waiter != NULL) {
        vTaskNotifyGiveFromISR(tx_waiter, &woken);
        portYIELD_FROM_ISR(woken);
    }
}

task_entry_t create_uart_broadcast_task(app_data_t *data)
{
    task_entry_t entry = {0};
    const BaseType_t status = xTaskCreate(uart_broadcast_task,
        "UART broadcast", UART_BROADCAST_STACK_SIZE, data,
        UART_BROADCAST_PRIO, &entry.handle);

    configASSERT(status == pdPASS);
    vTaskSuspend(entry.handle);
    entry.name = "uart_broadcast";
    return entry;
}
