#include "main.h"
extern TIM_HandleTypeDef htim6;

void NMI_Handler(void) { Error_Handler(); }
void HardFault_Handler(void) { Error_Handler(); }
void MemManage_Handler(void) { Error_Handler(); }
void BusFault_Handler(void) { Error_Handler(); }
void UsageFault_Handler(void) { Error_Handler(); }
void SysTick_Handler(void) { }
void TIM6_DAC_IRQHandler(void) { HAL_TIM_IRQHandler(&htim6); }
