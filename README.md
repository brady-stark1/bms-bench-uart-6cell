Members: Aagam Jain, Brady Stark

To compile the program, open the source code in STM32CubeIDE and click debug as on the project. To see the UART messaging, download PuTTY and change the settings to serial monitoring and a 115200 baud rate. This is done after properly hooking up the Custom BMS development board to a power supply.

External libraries: 

STM32CubeF4 HAL: configures GPIO, SPI, UART, clocks, and the timer.
ARM CMSIS and STM32F4 device headers: provide processor and peripheral definitions.
Newlib-nano C library: provides functions such as snprintf and memset, bundled with the Arm GNU toolchain.
