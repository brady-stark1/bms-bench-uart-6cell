"""Parsing, filtering and demo anomaly detection; independent of serial/UI."""
from collections import deque
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
from statistics import median

CELL_COUNT = 6
# Far below the 1 mV input resolution; avoid binary float threshold flicker.
EPSILON_V = 1e-9
LINE = re.compile(r"cell\[([1-6])\]=(?:(-?\d+\.\d{3}) V|(N/A))")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class DetectionConfig:
    positive_deviation_threshold_v: float = 0.050
    positive_consecutive_samples: int = 3
    growing_start_deviation_v: float = 0.015
    growing_min_step_v: float = 0.002
    growing_consecutive_samples: int = 4
    clear_deviation_v: float = 0.010
    clear_consecutive_samples: int = 3


@dataclass(frozen=True)
class Config:
    settings_label: str = "Demo/monitoring settings only — not BMS safety limits"
    serial_port: str = ""
    moving_average_window: int = 5
    frame_timeout_seconds: float = 2.5
    stale_after_seconds: float = 3.5
    reconnect_seconds: float = 2.0
    demo_interval_seconds: float = 1.0
    history_samples: int = 120
    recent_events: int = 50
    demo_monitoring: DetectionConfig = DetectionConfig()

    @classmethod
    def load(cls, path):
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("Config must be a JSON object")
        detection = values.pop("demo_monitoring", {})
        if not isinstance(detection, dict):
            raise ValueError("demo_monitoring must be a JSON object")
        config = cls(**values, demo_monitoring=DetectionConfig(**detection))
        config.validate()
        return config

    def validate(self):
        if not isinstance(self.serial_port, str) or not isinstance(self.settings_label, str):
            raise ValueError("serial_port and settings_label must be strings")
        for obj in (self, self.demo_monitoring):
            for field in fields(obj):
                value = getattr(obj, field.name)
                if field.name in ("settings_label", "serial_port", "demo_monitoring"):
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"{field.name} must be a finite number")
                is_count = field.name.endswith("samples") or field.name in (
                    "moving_average_window", "history_samples", "recent_events")
                if is_count and (not isinstance(value, int) or not 1 <= value <= 100000):
                    raise ValueError(f"{field.name} must be an integer from 1 to 100000")
                if value < 0 or (field.name.endswith("seconds") and value == 0):
                    raise ValueError(f"{field.name} must be positive (thresholds may be zero)")
        d = self.demo_monitoring
        if d.growing_consecutive_samples < 2:
            raise ValueError("growing_consecutive_samples must be at least 2")
        if d.clear_deviation_v >= min(d.positive_deviation_threshold_v, d.growing_start_deviation_v):
            raise ValueError("clear_deviation_v must be below both trigger thresholds")
        if self.stale_after_seconds < self.frame_timeout_seconds:
            raise ValueError("stale_after_seconds must be >= frame_timeout_seconds")


def parse_line(line):
    """Accept the exact signed three-decimal firmware format and N/A."""
    match = LINE.fullmatch(line.strip())
    if not match:
        return None
    value = float(match[2]) if match[2] is not None else None
    if value is not None and not math.isfinite(value):
        return None
    return int(match[1]), value


class Assembler:
    """Only ordered 1..6 reports qualify; cell 1 delimits reports on this UART."""
    def __init__(self, timeout):
        self.timeout = timeout
        self.reset()

    def reset(self):
        self.pending = []
        self.started = None

    def expire(self, now):
        if self.started is not None and now - self.started > self.timeout:
            self.reset()
            return True
        return False

    def feed(self, index, value, now):
        broken = self.expire(now)
        if index == 1:
            broken = broken or bool(self.pending)
            self.pending = [value]
            self.started = now
        elif self.pending and index == len(self.pending) + 1:
            self.pending.append(value)
        else:
            self.reset()
            return None, True
        if len(self.pending) == CELL_COUNT:
            report = self.pending
            self.reset()
            return report, broken
        return None, broken


class Detector:
    """Two independent event kinds per cell, both with low-threshold clearing."""
    def __init__(self, config):
        self.config = config
        self.active = {}
        self.sequence = 0
        self.break_sequence()

    def break_sequence(self):
        self.high_runs = [0] * CELL_COUNT
        self.growth_runs = [0] * CELL_COUNT
        self.previous = [None] * CELL_COUNT
        self.clear_runs = {}
        # An active event cannot be cleared by absent/invalid data.

    def update(self, deviations, timestamp, received_at):
        d = self.config
        events = []
        for cell, deviation in enumerate(deviations, 1):
            i = cell - 1
            self.high_runs[i] = self.high_runs[i] + 1 if deviation - d.positive_deviation_threshold_v > EPSILON_V else 0
            previous = self.previous[i]
            if deviation - d.growing_start_deviation_v > EPSILON_V:
                increasing = previous is not None and previous - d.growing_start_deviation_v > EPSILON_V and deviation - previous - d.growing_min_step_v > EPSILON_V
                self.growth_runs[i] = self.growth_runs[i] + 1 if increasing else 1
            else:
                self.growth_runs[i] = 0
            self.previous[i] = deviation
            for kind, triggered in (
                ("sustained_positive", self.high_runs[i] >= d.positive_consecutive_samples),
                ("growing", self.growth_runs[i] >= d.growing_consecutive_samples),
            ):
                key = (cell, kind)
                if key in self.active:
                    self.clear_runs[key] = self.clear_runs.get(key, 0) + 1 if deviation <= d.clear_deviation_v + EPSILON_V else 0
                    if self.clear_runs[key] >= d.clear_consecutive_samples:
                        event = dict(self.active.pop(key), transition="clear", timestamp=timestamp,
                                     received_at=received_at, deviation_v=deviation)
                        self.clear_runs.pop(key, None)
                        events.append(event)
                elif triggered:
                    self.sequence += 1
                    event = dict(event_id=self.sequence, cell=cell, kind=kind,
                                 label="Simulated voltage anomaly", transition="start",
                                 started_at=timestamp, timestamp=timestamp,
                                 received_at=received_at, deviation_v=deviation)
                    self.active[key] = event
                    self.clear_runs[key] = 0
                    events.append(event)
        return events


class Processor:
    def __init__(self, config):
        config.validate()
        self.config = config
        self.windows = [deque(maxlen=config.moving_average_window) for _ in range(CELL_COUNT)]
        self.detector = Detector(config.demo_monitoring)
        self.sample_number = 0

    def break_sequence(self):
        for window in self.windows:
            window.clear()
        self.detector.break_sequence()

    def process(self, raw, timestamp, received_at=None):
        if len(raw) != CELL_COUNT or any(v is None or not math.isfinite(v) for v in raw):
            self.break_sequence()
            return None, []
        for window, value in zip(self.windows, raw):
            window.append(value)
        smoothed = [sum(window) / len(window) for window in self.windows]
        mid = median(smoothed)
        deviations = [value - mid for value in smoothed]
        self.sample_number += 1
        sample = dict(sample_number=self.sample_number, timestamp=timestamp,
                      received_at=received_at or utc_now(), raw_v=list(raw),
                      smoothed_v=smoothed, median_v=mid, minimum_v=min(smoothed),
                      maximum_v=max(smoothed), spread_v=max(smoothed) - min(smoothed),
                      deviations_v=deviations, window_samples=len(self.windows[0]))
        events = self.detector.update(deviations, timestamp, sample["received_at"])
        return sample, events

    def active_events(self):
        return list(self.detector.active.values())

    def settings(self):
        return asdict(self.config)
