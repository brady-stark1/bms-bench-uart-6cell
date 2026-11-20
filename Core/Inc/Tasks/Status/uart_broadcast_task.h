#ifndef UART_BROADCAST_TASK_H
#define UART_BROADCAST_TASK_H

#include "app.h"

#define UART_BROADCAST_STACK_SIZE    (2U * KILOBYTE)
#define UART_BROADCAST_PERIOD_MS     1000U
#define UART_BROADCAST_CELL_COUNT    6U
/* Six signed 32-bit millivolt values fit within 192 bytes. */
#define UART_BROADCAST_BUFFER_BYTES  192U
#define UART_BROADCAST_TX_TIMEOUT_MS 1000U

/* Prints only cell voltages 1-6 once per second on USART1 (J5, 115200
 * 8N1). Indices are 1-based across the pack; unavailable cells print N/A.
 * Diagnostic only; it never blocks the critical task and is not part of
 * the watchdog-proven path. */
void uart_broadcast_task(void *argument);
task_entry_t create_uart_broadcast_task(app_data_t *data);

#endif /* UART_BROADCAST_TASK_H */
