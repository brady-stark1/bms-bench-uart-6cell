#include "main.h"
#include "bench_config.h"
#include "Peripherals/digital_pins.h"
#include "Voltage/bq79600_bridge.h"
#include "voltage_display.h"

static SPI_HandleTypeDef hspi1;
static UART_HandleTypeDef huart1;
static void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_SPI1_Init(void);
static void MX_USART1_UART_Init(void);

int main(void)
{
    bq79600_bringup_result_t bringup;
    uint8_t ready = 0U;
    uint32_t next_report;

    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_SPI1_Init();
    MX_USART1_UART_Init();
    next_report = HAL_GetTick();
    for (;;) {
        int32_t cells[BENCH_CELL_COUNT] = {0};
        char report[192];
        uint8_t valid = 0U;
        size_t length;

        if (ready == 0U) {
            ready = (bq79600_stack_bringup(&hspi1, BENCH_DEVICE_COUNT,
                &bringup) == BQ79600_BRINGUP_OK &&
                bq79600_configure_measurements(&hspi1, BENCH_DEVICE_COUNT,
                    BENCH_CELL_COUNT, &bringup) == BQ79600_BRINGUP_OK);
        }
        if (ready != 0U) {
            valid = (bq79600_read_cell_voltages(&hspi1, cells) ==
                BQ79600_BRINGUP_OK);
            /* Retry startup on the next cycle after a disconnected chain. */
            ready = valid;
        }
        length = voltage_display_format(report, sizeof(report), cells, valid);
        (void)HAL_UART_Transmit(&huart1, (uint8_t *)report,
            (uint16_t)length, BENCH_UART_TIMEOUT_MS);

        /* Absolute deadlines preserve the original one-second cadence. */
        next_report += BENCH_DISPLAY_PERIOD_MS;
        if ((int32_t)(HAL_GetTick() - next_report) >= 0) {
            next_report = HAL_GetTick() + BENCH_DISPLAY_PERIOD_MS;
        }
        while ((int32_t)(HAL_GetTick() - next_report) < 0) {
            __WFI();
        }
    }
}

static void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 8;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;
  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

static void MX_SPI1_Init(void)
{
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_16;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 10;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
}

static void MX_USART1_UART_Init(void)
{
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
}

static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef gpio = {0};
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();

    /* Keep the existing board's unused control outputs deasserted. */
    HAL_GPIO_WritePin(GPIOB, BENCH_UNUSED_OUTPUT_PINS, GPIO_PIN_RESET);
    gpio.Pin = BENCH_UNUSED_OUTPUT_PINS;
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOB, &gpio);

    HAL_GPIO_WritePin(AMS_AFE_CS_GPIO_PORT, AMS_AFE_CS_PIN, GPIO_PIN_SET);
    gpio.Pin = AMS_AFE_CS_PIN;
    gpio.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    HAL_GPIO_Init(AMS_AFE_CS_GPIO_PORT, &gpio);
    gpio.Pin = AMS_AFE_SPI_READY_PIN;
    gpio.Mode = GPIO_MODE_INPUT;
    HAL_GPIO_Init(AMS_AFE_SPI_READY_GPIO_PORT, &gpio);
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *timer)
{
    if (timer->Instance == TIM6) {
        HAL_IncTick();
    }
}

void Error_Handler(void)
{
    __disable_irq();
    for (;;) {
    }
}
