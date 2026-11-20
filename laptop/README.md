# EE 250 Formula Electric — laptop telemetry processing

This application receives the existing six-cell STM32 UART output and processes
it entirely on the laptop. The STM32 firmware, acquisition path, and UART output
are unchanged. The display and detector describe **simulated voltage anomalies
in resistor-ladder measurements**, not real battery faults. All configurable
thresholds are **demo/monitoring settings, not BMS safety limits**.

## Quick start: no hardware required

Use Python **3.10 or newer**. From the repository root:

```sh
python3 laptop/run.py --mode demo
```

Open **http://127.0.0.1:8765** in your browser. The server is local to this laptop.
On Windows, substitute `python` for `python3`. Demo/replay require no packages.
Stop the application with **Ctrl+C**; closing the browser does not stop logging.

The labeled demo produces 70 reports: 15 baseline, 15 with cell 3 rising,
20 with that cell remaining high, then 20 back at baseline. Both event types
start and later clear with the default settings. The final recovery phase
illustrates hysteresis. Playback finishes without looping; the dashboard stays
open and becomes stale when no new data arrives. To run faster:

```sh
python3 laptop/run.py --mode demo --speed 5
```

Demo and replay never import or open the serial transport. Every input mode
passes firmware-formatted lines through the same parser, report assembler,
processor, event detector, dashboard state, and CSV logger.

## Live serial setup

Create a virtual environment and install the sole external dependency:

```sh
python3 -m venv laptop/.venv
source laptop/.venv/bin/activate
python -m pip install -r laptop/requirements.txt
python laptop/run.py --list-ports
python laptop/run.py --mode serial --port /dev/cu.usbserial-EXAMPLE
```

On Windows, activate with `laptop\.venv\Scripts\Activate.ps1` in PowerShell and
use the listed port, for example `--port COM3`. On Linux it may be
`--port /dev/ttyUSB0`. Close other serial monitors first. Alternatively set
`serial_port` in `laptop/config.json`.

The port uses **115200 baud, 8 data bits, no parity, 1 stop bit, no XON/XOFF,
RTS/CTS, or DSR/DTR flow control**. There is no serial `write`, command protocol,
CAN transmission, MQTT, or hardware-control UI. Only the board TX and adapter
RX plus the common reference are needed for the existing receive connection;
leave the adapter TX, RTS and DTR unconnected. The application requests inactive
RTS/DTR before opening the port; some OS/adapter drivers can still pulse those
signals on opening ([pySerial behavior](https://pyserial.readthedocs.io/en/latest/pyserial_api.html#serial.Serial.open)).
It does not change them during acquisition. A disconnect is shown explicitly
and retried every two seconds by default.

The parser follows `Core/Src/voltage_display.c`, including signed values,
three decimal places, and CRLF line endings:

```text
cell[1]=3.700 V
cell[2]=3.701 V
cell[3]=N/A
cell[4]=3.702 V
cell[5]=3.700 V
cell[6]=3.698 V
```

An ordered report must begin with cell 1 and end with cell 6. N/A, malformed
lines, missing/duplicate/out-of-order cells, or a report taking longer than
`frame_timeout_seconds` prevent that report from reaching the processor.
The next cell 1 resynchronizes input. Serial timeouts and partial byte reads
are handled without accepting half a line. Overlong lines are discarded.
Because the firmware has no report ID or timestamp, the laptop cannot detect
every possible byte-loss pattern or recover the exact MCU measurement time.

## Processing and event definitions

Each complete valid report preserves its six raw voltages. Each cell has its
own moving average of the last `moving_average_window` accepted reports
(default **5**). During startup it averages the available 1–4 reports and shows
that window count. Detection also runs during this warm-up.

From the six smoothed voltages the processor calculates the median (mean of
the middle two values), minimum, maximum, spread (`max - min`), and signed
cell deviations (`smoothed_cell - median`). The dashboard shows raw readings
from the current incoming report separately from metrics for the last accepted
complete report. Labels and age indicate when retained metrics are historical.
N/A/missing inputs are blank in CSV and unavailable in the UI, never zero.

Two independent event types can be active for each cell:

- **Sustained positive**: deviation is strictly greater than
  `positive_deviation_threshold_v` for `positive_consecutive_samples`
  consecutive accepted reports.
- **Growing**: deviation is strictly above `growing_start_deviation_v` for
  `growing_consecutive_samples` consecutive accepted reports, and each step
  after the first strictly exceeds `growing_min_step_v`. A four-report run
  means four above-start reports with three increasing steps. A flat/falling
  step or insufficient increase restarts that run at the current report.
- **Clear**: either active type clears only after deviation is at or below
  `clear_deviation_v` for `clear_consecutive_samples` consecutive valid
  reports. The clear threshold must be below both trigger thresholds. A
  plateau above the clear threshold keeps an event active. A new event can
  start again after clearing.

A start timestamp is the **confirmation report time**, after the configured
run qualifies; `started_at` links a later clear to that confirmation. Event IDs
are unique within a logging session. Counts refer to accepted reports, not
elapsed seconds; smoothing and consecutive counts both add detection delay.
For example, a five-sample window at about 1 Hz spans about five seconds.

Invalid/incomplete reports, malformed input, disconnects, and stale data reset
all averaging windows and pending start/clear runs. They **do not clear active
events**; those remain visible with uncertain confirmation until valid data
satisfies the clear condition. No fresh valid report for `stale_after_seconds`
(default **3.5**) marks data stale. Connection status and data freshness are
separate: an open serial port can still provide stale/invalid data.

## Configuration and choosing demo thresholds from the ladder baseline

Edit `laptop/config.json`, then restart. `--config PATH` selects a separate
file so experiments need not overwrite defaults. Voltages are in **volts**;
`0.050` V = 50 mV. All detection settings live under `demo_monitoring`:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `positive_deviation_threshold_v` | 0.050 | Sustained positive deviation above median |
| `positive_consecutive_samples` | 3 | Reports required to confirm sustained event |
| `growing_start_deviation_v` | 0.015 | Minimum positive deviation for a growing run |
| `growing_min_step_v` | 0.002 | Minimum increase between successive deviations |
| `growing_consecutive_samples` | 4 | Reports in the increasing run |
| `clear_deviation_v` | 0.010 | Lower threshold used to clear either event |
| `clear_consecutive_samples` | 3 | Low-deviation reports required to clear |

To tune from your measurements:

1. Record several minutes with the ladder unchanged, the intended supply and
   wiring, and the intended moving-average window. Keep only a known normal
   baseline session; discard startup warm-up and invalid/stale periods.
2. Examine `deviation_1_v` through `deviation_6_v` in `samples.csv`. These
   already use the smoothed median. Measure each cell's normal range and its
   positive peaks. Ladder resistor tolerances may create a persistent offset;
   baseline deviations do not have to be zero.
3. Put the positive trigger above the largest normal positive deviation,
   with margin for observed noise/drift. Put the growing start above normal
   baseline variation and choose a minimum step larger than ordinary upward
   sample-to-sample noise. For example, if baseline deviations stay within
   ±4 mV and upward steps stay below 1 mV, the shipped 50 mV positive trigger,
   15 mV growing start, and 2 mV step are illustrative demo starting points.
   Those example baseline numbers are **not measured calibration results**.
4. Set the clear threshold high enough that the normal baseline can satisfy
   it, but lower than both starts. Choose start/clear counts longer than
   observed short noise bursts. For a baseline returning below 5 mV, a
   10 mV clear threshold for three reports provides separation from the
   example triggers. A larger persistent ladder offset needs different
   settings; a common threshold must accommodate all six cells.
5. Replay your normal capture and confirm it produces no events. Then use
   the labeled example rise, or a deliberately edited replay, to check start,
   plateau, recovery and clear timing. Repeat after changing the smoothing
   window. This assesses demo behavior, not battery protection performance.

The dashboard's heatmap uses signed deviation (blue below median, green near
median, amber above). Color intensity is scaled to the configured positive
trigger; only an event outline/list indicates a confirmed anomaly. All six
traces share a median reference, so common-mode rises may leave deviations
unchanged. This detector does not implement absolute voltage limits.

## CSV logs and replay

Each run creates a unique timestamped directory under `laptop/logs/`.
`--log-dir PATH` overrides that location. Files are flushed while running:

- **`readings.csv`**: every received line with reception/source UTC timestamps,
  mode, cell index, raw voltage or blank for N/A, parse status, and original
  text. This preserves invalid and incomplete reports for inspection.
- **`samples.csv`**: each complete valid report, raw/smoothed/deviation values
  for all six cells, median/min/max/spread, sample number and window count.
- **`events.csv`**: every start/clear transition, event ID, cell, event type,
  simulated-anomaly label, confirmation/start time and current deviation.
- **`session.json`**: mode and configuration snapshot, including thresholds,
  port or replay path, and playback speed.

Live timestamps are laptop UTC reception times, not timestamps from the MCU.
Demo timestamps are generated source times. Replay preserves source timestamps;
`received_at` separately records the current laptop time. Mode is included in
every CSV row so generated measurements cannot be confused with serial data.
Logs and virtual environments are ignored by Git.

Replay the included example or your own `samples.csv`:

```sh
python3 laptop/run.py --mode replay --replay laptop/examples/simulated_rise.csv
python3 laptop/run.py --mode replay --replay /path/to/samples.csv --speed 5
python3 laptop/run.py --mode demo --headless --speed 100
```

`--headless` processes/logs without a web server and exits when playback ends.
Live serial headless mode runs until Ctrl+C. Replay CSVs need `timestamp`
(ISO 8601 with UTC offset or `Z`) and `raw_1_v` through `raw_6_v`. Blank/N/A
cells invalidate that row; non-finite values and backward timestamps are
rejected. Recorded gaps exceeding the stale threshold reset the averaging
and detection runs even when replay is accelerated. `samples.csv` contains
only accepted reports, so it cannot reproduce the exact sequence of lost or
invalid UART lines; such gaps may only be inferred from timestamps. Raw-line
replay is not provided. Previously smoothed columns and recorded events are
ignored: replay recomputes results using the current configuration.

At speed 1, timestamp spacing is preserved. UI freshness uses elapsed laptop
time, so very slow playback can become stale between rows. Use the default
speed when comparing live stale behavior. `--http-port 8766` chooses another
local dashboard port if needed.

## Verification

```sh
python3 -m unittest discover -s laptop/tests -v
```

Tests cover exact firmware parsing, incomplete/N/A/duplicate/timeout handling,
five-sample averaging, median metrics, both detector types, hysteresis and
retriggering, stale/disconnect behavior, demo/replay, CSV contents, fragmented
serial reads, read-only HTTP handlers and serial settings/no-write behavior.
No connected hardware is needed. Live device access and measurement accuracy
still require a physical bench check.
