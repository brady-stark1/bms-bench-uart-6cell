"""Build the standalone voltage monitor with Arm GNU tools (no RTOS)."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
INCLUDES = [
    "Core/Inc", "Drivers/STM32F4xx_HAL_Driver/Inc",
    "Drivers/STM32F4xx_HAL_Driver/Inc/Legacy",
    "Drivers/CMSIS/Device/ST/STM32F4xx/Include", "Drivers/CMSIS/Include",
]
HAL_MODULES = [
    "hal", "hal_cortex", "hal_dma", "hal_flash", "hal_flash_ex",
    "hal_flash_ramfunc", "hal_gpio", "hal_pwr", "hal_pwr_ex", "hal_rcc",
    "hal_rcc_ex", "hal_spi", "hal_tim", "hal_tim_ex", "hal_uart",
]

def build(configuration, toolchain_bin=None):
    gcc = Path(toolchain_bin) / "arm-none-eabi-gcc" if toolchain_bin else shutil.which("arm-none-eabi-gcc")
    if gcc is None:
        raise SystemExit("Pass --toolchain-bin with your Arm GNU tools bin directory.")
    gcc = Path(gcc)
    suffix = ".exe" if (gcc.parent / "arm-none-eabi-gcc.exe").exists() else ""
    gcc = gcc.with_name("arm-none-eabi-gcc" + suffix)
    output = ROOT / ".build" / configuration
    output.mkdir(parents=True, exist_ok=True)
    architecture = ["-mcpu=cortex-m4", "-mthumb", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard"]
    options = ["-O0", "-g3", "-DDEBUG"] if configuration == "Debug" else ["-Os", "-g0"]
    sources = sorted(p for p in (ROOT / "Core").rglob("*") if p.suffix in (".c", ".s"))
    sources += [ROOT / "Drivers/STM32F4xx_HAL_Driver/Src" / ("stm32f4xx_" + module + ".c") for module in HAL_MODULES]
    objects = []
    for source in sources:
        relative = source.relative_to(ROOT)
        obj = output / "obj" / (str(relative) + ".o")
        obj.parent.mkdir(parents=True, exist_ok=True)
        command = [str(gcc), *architecture, *options, "-DUSE_HAL_DRIVER", "-DSTM32F405xx",
                   "-ffunction-sections", "-fdata-sections", "-Wall", "-Wextra", "--specs=nano.specs",
                   *["-I" + str(ROOT / directory) for directory in INCLUDES]]
        if relative.parts[0] == "Core":
            command.append("-Werror")
        command += ["-std=gnu11"] if source.suffix == ".c" else ["-x", "assembler-with-cpp"]
        subprocess.run([*command, "-c", str(source), "-o", str(obj)], check=True)
        objects.append(str(obj))
    elf = output / "bms_fsae.elf"
    subprocess.run([str(gcc), *architecture, "--specs=nano.specs", "--specs=nosys.specs",
                    "-T", str(ROOT / "STM32F405RGTX_FLASH.ld"),
                    "-Wl,-Map=" + str(output / "bms_fsae.map"), "-Wl,--gc-sections",
                    "-Wl,--print-memory-usage", "-static", *objects,
                    "-Wl,--start-group", "-lc", "-lm", "-Wl,--end-group", "-o", str(elf)], check=True)
    for fmt, extension in [("ihex", "hex"), ("binary", "bin")]:
        subprocess.run([str(gcc.parent / ("arm-none-eabi-objcopy" + suffix)), "-O", fmt,
                        str(elf), str(output / ("bms_fsae." + extension))], check=True)
    subprocess.run([str(gcc.parent / ("arm-none-eabi-size" + suffix)), str(elf)], check=True)
    manifest = {"configuration": configuration, "source_count": len(sources)}
    for extension in ("elf", "hex", "bin"):
        manifest[extension + "_sha256"] = hashlib.sha256((output / ("bms_fsae." + extension)).read_bytes()).hexdigest()
    (output / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Build completed:", elf)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", choices=["Debug", "Release"], default="Debug")
    parser.add_argument("--toolchain-bin")
    args = parser.parse_args()
    build(args.configuration, args.toolchain_bin)
