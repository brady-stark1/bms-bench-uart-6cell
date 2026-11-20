"""Local browser dashboard; all HTTP endpoints and serial data are read-only."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from dataclasses import asdict
from pathlib import Path
import threading

from .core import Config
from .runtime import CsvLogs, Monitor, acquisition

ROOT = Path(__file__).resolve().parents[1]


def handler_for(monitor):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/state":
                body = json.dumps(monitor.state(), allow_nan=False).encode("utf-8")
                mime = "application/json"
            elif self.path == "/":
                body = (ROOT / "bms_monitor" / "dashboard.html").read_bytes()
                mime = "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("serial", "demo", "replay"), default="demo")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--port", help="Live serial port, overriding config.serial_port")
    parser.add_argument("--replay", type=Path, help="CSV with timestamp and raw_1_v..raw_6_v")
    parser.add_argument("--speed", type=float, default=1.0, help="Demo/replay speed multiplier")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    parser.add_argument("--headless", action="store_true", help="Process and log without HTTP; playback exits at EOF")
    parser.add_argument("--list-ports", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = Config.load(args.config)
    except (ValueError, TypeError, OSError) as error:
        parser.error(f"Invalid configuration: {error}")
    import math
    if not math.isfinite(args.speed) or args.speed <= 0:
        parser.error("--speed must be a finite positive number")
    if not 0 <= args.http_port <= 65535:
        parser.error("--http-port must be between 0 and 65535")
    if args.mode == "serial" and args.speed != 1.0:
        parser.error("--speed applies only to demo/replay")
    serial_module = None
    if args.mode == "serial" or args.list_ports:
        try:
            import serial as serial_module
        except ImportError:
            parser.error("Live serial input needs pyserial: python -m pip install -r laptop/requirements.txt")
    if args.list_ports:
        from serial.tools import list_ports
        for port in list_ports.comports():
            print(f"{port.device}\t{port.description}")
        return 0
    port = args.port or config.serial_port
    if args.mode == "serial" and not port:
        parser.error("Serial mode requires --port or config.serial_port")
    if args.mode == "replay" and not args.replay:
        parser.error("Replay mode requires --replay CSV_PATH")
    if args.mode != "serial" and args.port:
        parser.error("--port is accepted only in serial mode; demo/replay never open serial")
    if args.mode != "replay" and args.replay:
        parser.error("--replay requires --mode replay")
    logs = CsvLogs(args.log_dir, args.mode)
    (logs.directory / "session.json").write_text(json.dumps(dict(
        mode=args.mode, port=port if args.mode == "serial" else None,
        replay=str(args.replay) if args.mode == "replay" else None,
        playback_speed=args.speed, config=asdict(config)), indent=2) + "\n", encoding="utf-8")
    monitor = Monitor(config, args.mode, logs)
    stop = threading.Event()
    worker = threading.Thread(target=acquisition, kwargs=dict(
        monitor=monitor, mode=args.mode, stop=stop, port=port, replay=args.replay,
        speed=args.speed, serial_module=serial_module), daemon=True)
    server = None
    try:
        if not args.headless:
            server = ThreadingHTTPServer(("127.0.0.1", args.http_port), handler_for(monitor))
            server.timeout = 0.25
            print(f"Dashboard: http://127.0.0.1:{server.server_port}", flush=True)
        print(f"Mode: {args.mode.upper()} • read-only • demo/monitoring settings, not BMS safety limits", flush=True)
        print(f"CSV logs: {logs.directory.resolve()}", flush=True)
        worker.start()
        if args.headless:
            while worker.is_alive():
                worker.join(0.25)
        else:
            while True:
                server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if worker.ident is not None:
            worker.join()
        if server is not None:
            server.server_close()
        logs.close()
    if monitor.connection == "error":
        print(monitor.message)
        return 1
    return 0
