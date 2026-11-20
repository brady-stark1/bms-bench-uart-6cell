"""Run voltage decoding, CRC and display tests with a native C compiler."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".build" / "voltage-host-tests"
TESTS = {
    "protocol": ["tests/host/test_bq796xx_protocol.c", "Core/Src/Voltage/bq796xx_protocol.c"],
    "measurement": ["tests/host/test_bq79616_measurement.c", "Core/Src/Voltage/bq79616_measurement.c", "Core/Src/Voltage/bq796xx_protocol.c"],
    "display": ["tests/host/test_voltage_display.c", "Core/Src/voltage_display.c"],
}
OUTPUT.mkdir(parents=True, exist_ok=True)
compiler = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
if compiler is None:
    raise SystemExit("Install a native C compiler or set CC.")
for name, sources in TESTS.items():
    executable = OUTPUT / (name + (".exe" if os.name == "nt" else ""))
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-ICore/Inc",
                    *sources, "-o", str(executable)], cwd=ROOT, check=True)
    subprocess.run([str(executable)], check=True)
    print("PASS", name)
