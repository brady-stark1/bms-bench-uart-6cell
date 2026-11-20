#include <assert.h>
#include <limits.h>
#include <string.h>
#include "voltage_display.h"

int main(void)
{
    char report[192];
    int32_t cells[BENCH_CELL_COUNT] = {3700, 3701, 3702, 3703, 3704, 3705};
    size_t length = voltage_display_format(report, sizeof(report), cells, 1U);
    assert(length == strlen(report));
    assert(strcmp(report, "cell[1]=3.700 V\r\ncell[2]=3.701 V\r\n"
        "cell[3]=3.702 V\r\ncell[4]=3.703 V\r\n"
        "cell[5]=3.704 V\r\ncell[6]=3.705 V\r\n") == 0);
    length = voltage_display_format(report, sizeof(report), cells, 0U);
    assert(length == strlen(report));
    assert(strcmp(report, "cell[1]=N/A\r\ncell[2]=N/A\r\ncell[3]=N/A\r\n"
        "cell[4]=N/A\r\ncell[5]=N/A\r\ncell[6]=N/A\r\n") == 0);
    for (unsigned i = 0; i < BENCH_CELL_COUNT; i++) cells[i] = INT32_MIN;
    length = voltage_display_format(report, sizeof(report), cells, 1U);
    assert(length < sizeof(report) - 1U);
    assert(strstr(report, "cell[6]=-2147483.648 V\r\n") != NULL);
    {
        char small[5] = {0};
        assert(voltage_display_format(small, sizeof(small), cells, 1U) == 4U);
        assert(small[4] == '\0');
    }
    assert(voltage_display_format(NULL, 0U, cells, 1U) == 0U);
    return 0;
}
