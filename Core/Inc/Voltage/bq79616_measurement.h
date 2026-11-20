#ifndef BQ79616_MEASUREMENT_H
#define BQ79616_MEASUREMENT_H

#include <stdint.h>

/* BQ79616-Q1 measurement registers (stack device side of the BQ79600). */
#define BQ79616_REG_ACTIVE_CELL              0x0003U
#define BQ79616_REG_ADC_CONF1                0x0007U
#define BQ79616_REG_ADC_CTRL1                0x030DU
#define BQ79616_REG_VCELL16_HI               0x0568U

#define BQ79616_MIN_CELLS                       6U
#define BQ79616_MAX_CELLS                      16U
/* LPF_VCELL = 26 Hz, which needs about 38 ms of averaging after MAIN_GO. */
#define BQ79616_ADC_CONF1_LPF_VCELL_26HZ     0x02U
#define BQ79616_LPF_VCELL_26HZ_SETTLE_US    38000U
/* LPF_VCELL_EN | MAIN_GO | MAIN_MODE = continuous. */
#define BQ79616_ADC_CTRL1_CONTINUOUS         0x0EU

/* Response frame: INIT, device, register (2), data, CRC (2). */
#define BQ79616_RESPONSE_OVERHEAD_BYTES         6U

typedef enum {
    BQ79616_DECODE_OK = 0,
    BQ79616_DECODE_INVALID_ARGUMENT,
    BQ79616_DECODE_BAD_FRAME,
    BQ79616_DECODE_BAD_CRC,
    BQ79616_DECODE_BAD_DEVICE
} bq79616_decode_status_t;

/* ACTIVE_CELL encodes the active cell count minus six. Returns 0 when cells
 * is outside 6-16 (callers must check the range first). */
uint8_t bq79616_active_cell_value(uint8_t cells);

/* First register of a block read that returns VCELL<cells> down to VCELL1. */
uint16_t bq79616_cell_block_address(uint8_t cells);

/* Bytes the BQ79600 returns for a stack read of channels 16-bit results. */
uint16_t bq79616_stack_response_bytes(uint8_t devices, uint8_t channels);

/* Convert signed cell ADC codes at 190.73 uV/LSB. */
int32_t bq79616_cell_code_to_mv(int16_t code);

/* Decode a stack response of one frame per device. Frames may arrive in any
 * device order; each device 1..devices must appear exactly once. Output is
 * indexed (device - 1) * channels + channel, channel 0 = cell 1. */
bq79616_decode_status_t bq79616_decode_cells(const uint8_t *response,
    uint16_t length, uint8_t devices, uint8_t cells, int32_t *cell_mv);
#endif /* BQ79616_MEASUREMENT_H */
