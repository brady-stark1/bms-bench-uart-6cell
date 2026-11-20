import csv
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bms_monitor.app import handler_for
from bms_monitor.core import Assembler, Config, DetectionConfig, Detector, Processor, parse_line
from bms_monitor.runtime import CsvLogs, Monitor, acquisition, demo_rows, feed_rows, open_serial, read_serial, replay_rows


class CoreTests(unittest.TestCase):
    def test_source_format_and_invalid_lines(self):
        self.assertEqual(parse_line('cell[1]=3.700 V\r\n'), (1, 3.7))
        self.assertEqual(parse_line('cell[6]=-0.019 V'), (6, -.019))
        self.assertEqual(parse_line('cell[2]=N/A'), (2, None))
        for line in ['cell[7]=3.700 V', 'cell[0]=3.700 V', 'cell[1]=nan V',
                     'cell[1]=3.7 V', 'cell[1]=3.700 A', 'junk', 'cell[1]=3.700 V junk']:
            self.assertIsNone(parse_line(line))

    def test_assembler_rejects_mixed_duplicate_and_timed_out_reports(self):
        a = Assembler(2.5)
        self.assertEqual(a.feed(3, 3.7, 0), (None, True))
        a.feed(1, 3.7, 0)
        self.assertEqual(a.feed(1, 3.8, 1), (None, True))
        self.assertEqual(a.feed(3, 3.7, 1), (None, True))
        a.feed(1, 3.7, 2)
        self.assertTrue(a.expire(5))
        self.assertEqual(a.feed(2, 3.7, 5), (None, True))
        for i in range(1, 7):
            report, broken = a.feed(i, None if i == 4 else 3.7, 6)
            self.assertFalse(broken)
        self.assertEqual(report, [3.7, 3.7, 3.7, None, 3.7, 3.7])

    def test_moving_average_metrics_and_gap_reset(self):
        p = Processor(Config(moving_average_window=2))
        p.process([1, 2, 3, 4, 5, 6], 't1')
        sample, _ = p.process([3, 4, 5, 6, 7, 8], 't2')
        self.assertEqual(sample['raw_v'], [3, 4, 5, 6, 7, 8])
        self.assertEqual(sample['smoothed_v'], [2, 3, 4, 5, 6, 7])
        self.assertEqual(sample['median_v'], 4.5)
        self.assertEqual(sample['minimum_v'], 2)
        self.assertEqual(sample['maximum_v'], 7)
        self.assertEqual(sample['spread_v'], 5)
        self.assertEqual(sample['deviations_v'], [-2.5, -1.5, -.5, .5, 1.5, 2.5])
        sample, _ = p.process([5] * 6, 't3')
        self.assertEqual(sample['smoothed_v'], [4, 4.5, 5, 5.5, 6, 6.5])
        self.assertEqual(p.process([None] * 6, 't4'), (None, []))
        sample, _ = p.process([3.7] * 6, 't5')
        self.assertEqual(sample['smoothed_v'], [3.7] * 6)
        self.assertEqual(sample['window_samples'], 1)

    def test_default_five_sample_window(self):
        p = Processor(Config())
        for i in range(1, 7):
            sample, _ = p.process([float(i)] * 6, str(i))
        self.assertEqual(sample['smoothed_v'], [4] * 6)
        self.assertEqual(sample['window_samples'], 5)

    def test_positive_detection_hysteresis_clear_and_retrigger(self):
        d = Detector(DetectionConfig(positive_deviation_threshold_v=.05,
            positive_consecutive_samples=3, growing_start_deviation_v=1,
            clear_deviation_v=.01, clear_consecutive_samples=2))
        update = lambda v: d.update([v, 0, 0, 0, 0, 0], 'timestamp', 'received')
        self.assertFalse(update(.05))  # Strictly above threshold.
        self.assertFalse(update(.06))
        self.assertFalse(update(.06))
        events = update(.06)
        self.assertEqual([(e['transition'], e['cell']) for e in events], [('start', 1)])
        event_id = events[0]['event_id']
        self.assertFalse(update(.04))  # Below trigger, above clear: remains active.
        self.assertFalse(update(.005))
        self.assertFalse(update(.02))  # Breaks clear sequence.
        self.assertFalse(update(-.01))
        events = update(.005)
        self.assertEqual(events[0]['transition'], 'clear')
        self.assertEqual(events[0]['event_id'], event_id)
        for _ in range(3):
            events = update(.06)
        self.assertGreater(events[0]['event_id'], event_id)

    def test_growth_requires_consecutive_increasing_samples_and_latches(self):
        d = Detector(DetectionConfig(positive_deviation_threshold_v=1,
            growing_start_deviation_v=.015, growing_min_step_v=.002,
            growing_consecutive_samples=3))
        update = lambda v: d.update([0, 0, v, 0, 0, 0], 't', 'r')
        self.assertFalse(update(.02))
        self.assertFalse(update(.025))
        self.assertFalse(update(.024))  # Falling sample restarts run.
        self.assertFalse(update(.03))
        events = update(.04)
        self.assertEqual(events[0]['kind'], 'growing')
        self.assertEqual(events[0]['cell'], 3)
        for _ in range(5):
            self.assertFalse(update(.04))  # Plateau does not clear an active event.
        self.assertEqual(len(d.active), 1)

    def test_gaps_reset_pending_and_clear_counts_but_keep_active(self):
        d = Detector(DetectionConfig(positive_consecutive_samples=2))
        update = lambda v: d.update([v, 0, 0, 0, 0, 0], 't', 'r')
        update(.1)
        d.break_sequence()
        self.assertFalse(update(.1))
        self.assertEqual(update(.1)[0]['transition'], 'start')
        update(0)
        update(0)
        d.break_sequence()
        self.assertFalse(update(0))
        self.assertEqual(len(d.active), 1)
        update(0)
        self.assertEqual(update(0)[0]['transition'], 'clear')

    def test_threshold_roundoff_does_not_trigger_on_equality(self):
        config = Config(moving_average_window=1, demo_monitoring=DetectionConfig(
            positive_consecutive_samples=1, growing_start_deviation_v=1))
        p = Processor(config)
        # 3.700 - 3.650 is slightly greater than .050 in binary floating point.
        _, events = p.process([3.700, 3.650, 3.650, 3.650, 3.650, 3.650], 't')
        self.assertEqual(events, [])
        _, events = p.process([3.701, 3.650, 3.650, 3.650, 3.650, 3.650], 't2')
        self.assertEqual(events[0]['kind'], 'sustained_positive')

    def test_config_rejects_invalid_settings(self):
        for config in [replace(Config(), moving_average_window=0),
                       replace(Config(), moving_average_window=True),
                       replace(Config(), stale_after_seconds=float('nan')),
                       replace(Config(), frame_timeout_seconds=10),
                       replace(Config(), demo_monitoring=DetectionConfig(clear_deviation_v=.1)),
                       replace(Config(), demo_monitoring=DetectionConfig(growing_consecutive_samples=1))]:
            with self.assertRaises(ValueError):
                config.validate()
        Config().validate()
        config = Config.load(Path(__file__).resolve().parents[1] / 'config.json')
        self.assertEqual(config.moving_average_window, 5)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.logs = CsvLogs(self.temp.name, 'demo')
        self.now = 0
        self.monitor = Monitor(Config(moving_average_window=1), 'demo', self.logs, clock=lambda: self.now)

    def tearDown(self):
        self.logs.close()
        self.temp.cleanup()

    def report(self, values):
        for i, value in enumerate(values, 1):
            self.monitor.feed(f'cell[{i}]=N/A' if value is None else f'cell[{i}]={value:.3f} V', '2026-01-01T00:00:00+00:00')

    def test_incomplete_and_na_never_produce_zero_or_new_sample(self):
        self.report([3.7] * 6)
        self.report([None] * 6)
        self.monitor.feed('cell[1]=3.800 V')
        self.monitor.feed('cell[2]=3.800 V')
        self.report([3.9] * 6)
        self.assertEqual(self.monitor.latest['sample_number'], 2)
        self.assertEqual(self.monitor.latest['raw_v'], [3.9] * 6)
        self.assertGreater(self.monitor.dropped_reports, 0)
        self.assertEqual(self.monitor.invalid_reports, 1)
        with (self.logs.directory / 'readings.csv').open() as f:
            lines = list(csv.DictReader(f))
        self.assertEqual(sum(row['parse_status'] == 'N/A' and row['raw_v'] == '' for row in lines), 6)
        with (self.logs.directory / 'samples.csv').open() as f:
            self.assertEqual(len(list(csv.DictReader(f))), 2)

    def test_stale_keeps_events_but_breaks_evidence(self):
        for _ in range(3):
            self.report([3.8, 3.7, 3.7, 3.7, 3.7, 3.7])
        self.assertEqual(len(self.monitor.processor.active_events()), 1)
        self.now = 4
        state = self.monitor.state()
        self.assertTrue(state['data_stale'])
        self.assertEqual(len(state['active_events']), 1)
        self.assertEqual(len(self.monitor.processor.windows[0]), 0)
        self.report([3.7] * 6)
        self.assertFalse(self.monitor.state()['data_stale'])
        self.assertEqual(len(self.monitor.processor.active_events()), 1)

    def test_timeout_and_malformed_break_frame(self):
        self.monitor.feed('cell[1]=3.700 V')
        self.now = 3
        self.monitor.poll()
        self.assertEqual(self.monitor.dropped_reports, 1)
        self.monitor.feed('cell[1]=3.700 V')
        self.monitor.feed('malformed')
        for i in range(2, 7):
            self.monitor.feed(f'cell[{i}]=3.700 V')
        self.assertIsNone(self.monitor.latest)
        self.assertEqual(self.monitor.malformed_lines, 1)

    def test_demo_uses_common_path_and_records_start_and_clear(self):
        acquisition(self.monitor, 'demo', threading.Event(), speed=100000)
        self.assertEqual(self.monitor.latest['sample_number'], 70)
        self.assertEqual(self.monitor.connection, 'finished')
        events = list(self.monitor.events)
        self.assertEqual({e['kind'] for e in events}, {'growing', 'sustained_positive'})
        self.assertEqual({e['transition'] for e in events}, {'start', 'clear'})
        self.assertTrue(all(e['cell'] == 3 for e in events))
        self.assertFalse(self.monitor.processor.active_events())
        with (self.logs.directory / 'events.csv').open() as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row['label'] == 'Simulated voltage anomaly' and row['mode'] == 'demo' for row in rows))
        replay = list(replay_rows(self.logs.directory / 'samples.csv'))
        self.assertEqual(len(replay), 70)
        self.assertEqual(replay[0][1], self.monitor.history[0]['raw_v'])

    def test_replay_fixture_matches_demo_and_checks_rows(self):
        rows = list(replay_rows(Path(__file__).resolve().parents[1] / 'examples/simulated_rise.csv'))
        self.assertEqual(len(rows), 70)
        for (_, actual), (_, expected) in zip(rows, demo_rows()):
            self.assertEqual(actual, [round(v, 3) for v in expected])
        path = Path(self.temp.name) / 'bad.csv'
        path.write_text('timestamp,raw_1_v,raw_2_v,raw_3_v,raw_4_v,raw_5_v,raw_6_v\n2026-01-01T00:00:00Z,nan,1,1,1,1,1\n')
        with self.assertRaises(ValueError):
            list(replay_rows(path))
        path.write_text('wrong,headers\n1,2\n')
        with self.assertRaises(ValueError):
            list(replay_rows(path))

    def test_serial_config_and_fragmented_reads_never_write(self):
        stop = threading.Event()
        device = Mock()
        device.__enter__ = Mock(return_value=device)
        device.__exit__ = Mock(return_value=False)
        payload = b''.join(f'cell[{i}]=3.700 V\r\n'.encode() for i in range(1, 7))
        chunks = iter([payload[:9], b'', payload[9:43], payload[43:]])
        def read(_size):
            try:
                return next(chunks)
            except StopIteration:
                stop.set()
                return b''
        device.read.side_effect = read
        serial = Mock(EIGHTBITS=8, PARITY_NONE='N', STOPBITS_ONE=1, SerialException=OSError)
        serial.Serial.return_value = device
        read_serial(self.monitor, 'FAKE_READ_ONLY_PORT', stop, serial)
        kwargs = serial.Serial.call_args.kwargs
        self.assertEqual((kwargs['baudrate'], kwargs['bytesize'], kwargs['parity'], kwargs['stopbits']), (115200, 8, 'N', 1))
        self.assertFalse(kwargs['xonxoff'] or kwargs['rtscts'] or kwargs['dsrdtr'])
        device.write.assert_not_called()
        self.assertEqual(device.dtr, False)
        self.assertEqual(device.rts, False)
        self.assertEqual(self.monitor.latest['raw_v'], [3.7] * 6)

    def test_serial_disconnect_sets_status_and_resets_processing(self):
        self.report([3.7] * 6)
        stop = threading.Event()
        serial = Mock(SerialException=OSError)
        def fail():
            stop.set()
            raise OSError('unplugged')
        serial.Serial.return_value.open.side_effect = fail
        read_serial(self.monitor, 'FAKE', stop, serial)
        self.assertEqual(self.monitor.connection, 'disconnected')
        self.assertTrue(self.monitor.stale)
        self.assertIn('unplugged', self.monitor.message)
        self.assertFalse(self.monitor.processor.windows[0])

    def test_recorded_gaps_reset_window_even_in_fast_replay(self):
        config = Config(moving_average_window=5)
        monitor = Monitor(config, 'replay', self.logs)
        rows = [('2026-01-01T00:00:00Z', [3.7] * 6),
                ('2026-01-01T00:00:01Z', [3.8] * 6),
                ('2026-01-01T00:01:00Z', [3.9] * 6)]
        feed_rows(monitor, rows, threading.Event(), speed=1000000)
        self.assertEqual(monitor.latest['window_samples'], 1)
        self.assertEqual(monitor.latest['smoothed_v'], [3.9] * 6)

    def test_read_only_http_api(self):
        self.report([3.7] * 6)
        Handler = handler_for(self.monitor)
        handler = object.__new__(Handler)
        handler.path = '/api/state'
        handler.wfile = BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.do_GET()
        state = json.loads(handler.wfile.getvalue())
        self.assertEqual(state['latest']['median_v'], 3.7)
        self.assertFalse(hasattr(Handler, 'do_POST'))
        handler.path = '/'; handler.wfile = BytesIO(); handler.do_GET()
        self.assertIn(b'Six-cell heatmap', handler.wfile.getvalue())
        self.assertIn(b'DEMO', handler.wfile.getvalue())


if __name__ == '__main__':
    unittest.main()
