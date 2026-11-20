#include <assert.h>
#include <string.h>

#include "Voltage/bq79616_measurement.h"
#include "Voltage/bq796xx_protocol.h"

static uint16_t put_frame(uint8_t *frame, uint8_t device, uint16_t address,
    const uint16_t *codes, uint8_t count)
{
    uint16_t position = 0U;
    uint8_t index;
    uint16_t crc;

    frame[position++] = (uint8_t)(count * 2U - 1U);
    frame[position++] = device;
    frame[position++] = (uint8_t)(address >> 8);
    frame[position++] = (uint8_t)address;
    for (index = 0U; index < count; index++) {
        frame[position++] = (uint8_t)(codes[index] >> 8);
        frame[position++] = (uint8_t)codes[index];
    }
    crc = bq796xx_crc16(frame, position);
    frame[position++] = (uint8_t)crc;
    frame[position++] = (uint8_t)(crc >> 8);
    return position;
}

static void test_register_helpers(void)
{

    assert(bq79616_active_cell_value(6U) == 0x00U);
    assert(bq79616_active_cell_value(16U) == 0x0AU);
    assert(bq79616_cell_block_address(16U) == 0x0568U);
    assert(bq79616_cell_block_address(6U) == 0x057CU);
    assert(bq79616_stack_response_bytes(1U, 6U) == 18U);


}

static void test_code_conversion(void)
{
    /* 0x4B00 = 19200 codes * 190.73 uV = 3662.0 mV */
    assert(bq79616_cell_code_to_mv(0x4B00) == 3662);
    assert(bq79616_cell_code_to_mv(0) == 0);
    assert(bq79616_cell_code_to_mv(-100) == -19);

}

static void test_decode_one_device_six_cells(void)
{
    /* Wire order is VCELL6 first, down to VCELL1. */
    const uint16_t codes[6] = {0x4E20U, 0x4D58U, 0x4C90U, 0x4BC8U,
        0x4B00U, 0x4A38U};
    uint8_t response[32];
    int32_t cells[6] = {0};
    const uint16_t length = put_frame(response, 1U,
        bq79616_cell_block_address(6U), codes, 6U);

    assert(length == bq79616_stack_response_bytes(1U, 6U));
    assert(bq79616_decode_cells(response, length, 1U, 6U, cells) ==
        BQ79616_DECODE_OK);
    assert(cells[0] == bq79616_cell_code_to_mv(0x4A38));
    assert(cells[1] == 3662);
    assert(cells[5] == bq79616_cell_code_to_mv(0x4E20));

    response[5] ^= 0x01U;
    assert(bq79616_decode_cells(response, length, 1U, 6U, cells) ==
        BQ79616_DECODE_BAD_CRC);
    assert(bq79616_decode_cells(response, (uint16_t)(length - 1U), 1U, 6U,
        cells) == BQ79616_DECODE_BAD_FRAME);
    assert(bq79616_decode_cells(response, length, 1U, 5U, cells) ==
        BQ79616_DECODE_INVALID_ARGUMENT);
}

int main(void)
{
    test_register_helpers();
    test_code_conversion();
    test_decode_one_device_six_cells();
    return 0;
}
