#ifndef VOLTAGE_DISPLAY_H
#define VOLTAGE_DISPLAY_H
#include <stddef.h>
#include <stdint.h>
#include "bench_config.h"
/* One line per differential ladder section; invalid reads produce N/A. */
size_t voltage_display_format(char *buffer, size_t capacity,
    const int32_t cell_mv[BENCH_CELL_COUNT], uint8_t valid);
#endif
