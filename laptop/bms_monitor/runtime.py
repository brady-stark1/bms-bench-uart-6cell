"""Input adapters, read-only runtime state and timestamped CSV logs."""
from collections import deque
import csv
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import threading
import time

from .core import Assembler, CELL_COUNT, Processor, parse_line, utc_now


def parse_timestamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Replay timestamps must include a UTC offset or Z")
    return stamp.astimezone(timezone.utc)


class CsvLogs:
    def __init__(self, root, mode):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        self.directory = Path(root) / f"{stamp}-{mode}"
        self.directory.mkdir(parents=True, exist_ok=False)
        self.files = []
        self.mode = mode
        self.lines = self._writer("readings.csv", ["received_at", "timestamp", "mode", "cell", "raw_v", "parse_status", "uart_line"])
        self.sample_fields = ["timestamp", "received_at", "mode", "sample_number", "window_samples"]
        self.sample_fields += [f"{kind}_{i}_v" for kind in ("raw", "smoothed", "deviation") for i in range(1, 7)]
        self.sample_fields += ["median_v", "minimum_v", "maximum_v", "spread_v"]
        self.samples = self._writer("samples.csv", self.sample_fields)
        self.events = self._writer("events.csv", ["timestamp", "received_at", "mode", "event_id", "transition", "cell", "kind", "label", "started_at", "deviation_v"])

    def _writer(self, name, fields):
        handle = (self.directory / name).open("w", newline="", encoding="utf-8")
        self.files.append(handle)
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        return writer

    def line(self, line, parsed, timestamp, received_at):
        self.lines.writerow(dict(timestamp=timestamp, received_at=received_at, mode=self.mode,
                                 cell=parsed[0] if parsed else "", raw_v=parsed[1] if parsed and parsed[1] is not None else "",
                                 parse_status=("valid" if parsed[1] is not None else "N/A") if parsed else "malformed",
                                 uart_line=line))

    def sample(self, sample):
        row = {key: sample[key] for key in ("timestamp", "received_at", "sample_number", "window_samples", "median_v", "minimum_v", "maximum_v", "spread_v")}
        row["mode"] = self.mode
        for kind, field in (("raw", "raw_v"), ("smoothed", "smoothed_v"), ("deviation", "deviations_v")):
            row.update({f"{kind}_{i}_v": value for i, value in enumerate(sample[field], 1)})
        self.samples.writerow(row)

    def event(self, event):
        self.events.writerow(dict(event, mode=self.mode))

    def flush(self):
        for handle in self.files:
            handle.flush()

    def close(self):
        for handle in self.files:
            handle.close()


class Monitor:
    def __init__(self, config, mode, logs, clock=time.monotonic):
        self.config, self.mode, self.logs, self.clock = config, mode, logs, clock
        self.lock = threading.RLock()
        self.processor = Processor(config)
        self.assembler = Assembler(config.frame_timeout_seconds)
        self.history = deque(maxlen=config.history_samples)
        self.events = deque(maxlen=config.recent_events)
        self.latest = None
        self.raw_live = [None] * CELL_COUNT
        self.connection = "starting"
        self.message = "Waiting for input"
        self.report_status = "waiting"
        self.last_line = self.last_valid = None
        self.stale = True
        self.dropped_reports = 0
        self.malformed_lines = 0
        self.invalid_reports = 0

    def _break(self, message):
        self.processor.break_sequence()
        self.report_status = message

    def connection_status(self, status, message):
        with self.lock:
            self.connection, self.message = status, message
            if status in ("disconnected", "error"):
                self.assembler.reset()
                self.raw_live = [None] * CELL_COUNT
                self._break(status)
                self.stale = True

    def source_gap(self):
        with self.lock:
            self.assembler.reset()
            self.raw_live = [None] * CELL_COUNT
            self._break("recorded data gap")

    def feed(self, line, timestamp=None):
        with self.lock:
            now = self.clock()
            timestamp = timestamp or utc_now()
            received_at = utc_now()
            parsed = parse_line(line)
            self.logs.line(line, parsed, timestamp, received_at)
            self.last_line = now
            if parsed is None:
                self.malformed_lines += 1
                self.assembler.reset()
                self.raw_live = [None] * CELL_COUNT
                self._break("malformed input")
                self.logs.flush()
                return
            index, value = parsed
            if index == 1:
                self.raw_live = [None] * CELL_COUNT
            self.raw_live[index - 1] = value
            report, broken = self.assembler.feed(index, value, now)
            if broken:
                self.dropped_reports += 1
                self._break("incomplete report")
            if value is None:
                self._break("invalid reading (N/A)")
            elif self.report_status != "invalid reading (N/A)" or index == 1:
                self.report_status = "assembling report"
            if report is not None:
                if any(v is None for v in report):
                    self.invalid_reports += 1
                    self._break("invalid report (N/A)")
                else:
                    sample, events = self.processor.process(report, timestamp, received_at)
                    self.latest = sample
                    self.history.append(sample)
                    self.last_valid = now
                    self.stale = False
                    self.report_status = "valid report"
                    self.logs.sample(sample)
                    for event in events:
                        self.events.appendleft(event)
                        self.logs.event(event)
            self.logs.flush()

    def poll(self):
        with self.lock:
            now = self.clock()
            if self.assembler.expire(now):
                self.dropped_reports += 1
                self._break("incomplete report timed out")
                self.raw_live = [None] * CELL_COUNT
            if self.last_valid is not None and now - self.last_valid > self.config.stale_after_seconds and not self.stale:
                self.stale = True
                self.assembler.reset()
                self._break("data stale")
                self.raw_live = [None] * CELL_COUNT

    def state(self):
        with self.lock:
            self.poll()
            now = self.clock()
            return dict(mode=self.mode, connection=self.connection, message=self.message,
                        data_stale=self.stale, report_status=self.report_status,
                        last_valid_age_seconds=None if self.last_valid is None else max(0, now - self.last_valid),
                        last_line_age_seconds=None if self.last_line is None else max(0, now - self.last_line),
                        raw_live_v=list(self.raw_live), latest=self.latest,
                        history=list(self.history), events=list(self.events),
                        active_events=self.processor.active_events(),
                        dropped_reports=self.dropped_reports, invalid_reports=self.invalid_reports,
                        malformed_lines=self.malformed_lines, settings=self.processor.settings(),
                        log_directory=str(self.logs.directory.resolve()))


def demo_rows(interval=1.0):
    """15 baseline, 15 rising, 20 high, 20 recovered samples; no hardware."""
    start = datetime.now(timezone.utc)
    for index in range(70):
        rise = 0.0 if index < 15 or index >= 50 else min((index - 14) * 0.008, 0.120)
        cells = [3.700 + round(0.001 * math.sin(index * 0.7 + cell), 3) for cell in range(6)]
        cells[2] += rise
        yield (start + timedelta(seconds=index * interval)).isoformat(timespec="milliseconds"), cells


def replay_rows(path):
    """Replay raw columns from our samples.csv (also accepts blank/N/A cells)."""
    previous = None
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = ["timestamp"] + [f"raw_{i}_v" for i in range(1, 7)]
        if not reader.fieldnames or not set(required) <= set(reader.fieldnames):
            raise ValueError("Replay CSV needs timestamp and raw_1_v through raw_6_v columns")
        for number, row in enumerate(reader, 2):
            try:
                stamp = parse_timestamp(row["timestamp"])
                cells = [None if row[f"raw_{i}_v"].strip() in ("", "N/A") else float(row[f"raw_{i}_v"]) for i in range(1, 7)]
                if any(value is not None and not math.isfinite(value) for value in cells):
                    raise ValueError("non-finite voltage")
                if previous is not None and stamp < previous:
                    raise ValueError("timestamps must be nondecreasing")
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError(f"Invalid replay row {number}: {error}") from error
            previous = stamp
            yield stamp.isoformat(timespec="milliseconds"), cells


def feed_rows(monitor, rows, stop, speed=1.0):
    previous = None
    for timestamp, cells in rows:
        stamp = parse_timestamp(timestamp)
        delay = 0 if previous is None else (stamp - previous).total_seconds() / speed
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if stop.wait(min(0.1, max(0, deadline - time.monotonic()))):
                return
            monitor.poll()
        if stop.is_set():
            return
        if previous is not None and (stamp - previous).total_seconds() > monitor.config.stale_after_seconds:
            monitor.source_gap()
        # Preserve invalid/partial-frame and parser behavior through the UART path.
        for cell, value in enumerate(cells, 1):
            line = f"cell[{cell}]=N/A" if value is None else f"cell[{cell}]={value:.3f} V"
            monitor.feed(line, timestamp)
        previous = stamp


def open_serial(port, serial_module):
    """No UART write path, software flow-control bytes, or command channel."""
    device = serial_module.Serial(port=None, baudrate=115200,
                                  bytesize=serial_module.EIGHTBITS,
                                  parity=serial_module.PARITY_NONE,
                                  stopbits=serial_module.STOPBITS_ONE,
                                  timeout=0.2, xonxoff=False, rtscts=False, dsrdtr=False)
    device.dtr = False
    device.rts = False
    device.port = port
    try:
        device.open()
    except Exception:
        device.close()
        raise
    return device


def read_serial(monitor, port, stop, serial_module):
    while not stop.is_set():
        try:
            with open_serial(port, serial_module) as device:
                monitor.connection_status("connected", f"{port} • 115200 8N1 • receive only")
                buffer = bytearray()
                discarding = False
                while not stop.is_set():
                    chunk = device.read(256)
                    for byte in chunk:
                        if byte == 10:
                            if not discarding:
                                monitor.feed(buffer.decode("ascii", errors="replace").rstrip("\r"))
                            buffer.clear()
                            discarding = False
                        elif not discarding:
                            buffer.append(byte)
                            if len(buffer) > 256:
                                monitor.feed("[discarded overlong UART line]")
                                buffer.clear()
                                discarding = True
                    monitor.poll()
        except (serial_module.SerialException, OSError) as error:
            monitor.connection_status("disconnected", f"{error}; retrying in {monitor.config.reconnect_seconds:g}s")
            stop.wait(monitor.config.reconnect_seconds)


def acquisition(monitor, mode, stop, port=None, replay=None, speed=1.0, serial_module=None):
    try:
        if mode == "serial":
            read_serial(monitor, port, stop, serial_module)
        else:
            label = "DEMO — generated simulated measurements" if mode == "demo" else "REPLAY — recorded measurements, no hardware"
            monitor.connection_status("playing", label)
            rows = demo_rows(monitor.config.demo_interval_seconds) if mode == "demo" else replay_rows(replay)
            feed_rows(monitor, rows, stop, speed)
            monitor.connection_status("finished", label + " • playback finished")
    except Exception as error:
        monitor.connection_status("error", f"{type(error).__name__}: {error}")
