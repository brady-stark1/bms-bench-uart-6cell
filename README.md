# Six-channel resistor-ladder voltage monitor

Standalone STM32F405RG bench firmware for the existing Custom_BMS motherboard,
BQ79600 SPI bridge and **one BQ79616 daughterboard**. The ladder connects to
the daughterboard's cell inputs, using the same interface as the original
firmware. It is not configured for the STM32's own analog pins.

The application wakes and addresses the chain, enables continuous conversion
of cell inputs 1-6, reads the latest six results, validates their frames/CRC,
and prints their voltages once per second. `cell[n]` is the voltage difference
between adjacent ladder taps (VCn and VCn-1), not each tap's voltage to ground.
The existing daughterboard wiring and BQ79616 input/power requirements still
apply; reducing the firmware does not change them.

## Serial output

Connect the existing J5 USART1 TX (PA9) and ground to your serial adapter.
Use **115200 baud, 8 data bits, no parity, 1 stop bit**.

```text
cell[1]=3.700 V
cell[2]=3.701 V
cell[3]=3.699 V
cell[4]=3.702 V
cell[5]=3.700 V
cell[6]=3.698 V
```

Only these six lines are printed per report. Startup/read failures print
`cell[n]=N/A` for all six channels and retry startup next cycle. Old readings
are not reused after a failed read. Conversions run continuously; a blocking,
timeout-bounded SPI read and UART write run on a 1000 ms absolute schedule.
After an overrun, the next deadline starts a fresh one-second interval.

## What remains

- `Core/Src/main.c`: board clock, GPIO, SPI, UART and measurement/display loop.
- `Core/Src/Voltage/`: BQ startup, cell configuration, SPI reads, CRC and decoding.
- `Core/Src/voltage_display.c`: six-line formatting, including unavailable reads.
- `Core/Inc/bench_config.h`: one device, six cells and the update period.
- STM32 startup, HAL timebase, linker support and vendor HAL/CMSIS libraries.

CAN, SOC, battery/charge/fan control, balancing, current/temperature sensing,
flash configuration storage, watchdog supervision and FreeRTOS have been
removed. The old board's control outputs are held low at initialization.
This project is a bench voltage monitor, with no battery protection/control.
The original application remains in Git history.

## Build and test

With Python 3 and Arm GNU tools on PATH:

```sh
python3 tools/build.py --configuration Debug
python3 tools/build.py --configuration Release
python3 tools/test-host.py
```

Use `--toolchain-bin "/path/to/arm/tools/bin"` when the compiler is not on
PATH (including the tools bundled with STM32CubeIDE). On Windows, use
`python` or the `tools/build.ps1` and `tools/test-host.ps1` wrappers.
Host tests need a native C compiler; set `CC` if necessary.

Build outputs are `.build/Debug/bms_fsae.{elf,hex,bin}` and the equivalent
Release directory. STM32CubeIDE project files are retained for importing and
building. Peripheral setup is maintained directly in C; the former CubeMX
`.ioc` configuration was removed because it generated the old BMS/RTOS setup.

Host tests cover frame CRC, six-channel ordering, millivolt conversion,
invalid/missing readings and serial formatting bounds. Builds and host tests
do not establish hardware measurement accuracy; verify readings on the ladder.
