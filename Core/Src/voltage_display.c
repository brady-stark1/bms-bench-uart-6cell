#include "voltage_display.h"
#include <stdio.h>

size_t voltage_display_format(char *buffer, size_t capacity,
    const int32_t cell_mv[BENCH_CELL_COUNT], uint8_t valid)
{
    size_t length = 0U;
    if (buffer == NULL || capacity == 0U) {
        return 0U;
    }
    buffer[0] = '\0';
    for (unsigned index = 0U; index < BENCH_CELL_COUNT; index++) {
        int written;
        if (valid != 0U && cell_mv != NULL) {
            const int32_t value = cell_mv[index];
            const uint32_t magnitude = value < 0 ?
                (uint32_t)(-(int64_t)value) : (uint32_t)value;
            written = snprintf(buffer + length, capacity - length,
                "cell[%u]=%s%lu.%03lu V\r\n", index + 1U,
                value < 0 ? "-" : "",
                (unsigned long)(magnitude / 1000U),
                (unsigned long)(magnitude % 1000U));
        } else {
            written = snprintf(buffer + length, capacity - length,
                "cell[%u]=N/A\r\n", index + 1U);
        }
        if (written < 0) {
            return length;
        }
        if ((size_t)written >= capacity - length) {
            return capacity - 1U;
        }
        length += (size_t)written;
    }
    return length;
}
