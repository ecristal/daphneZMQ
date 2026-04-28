#!/usr/bin/env python3
"""
On-board helper to test reclaimed PS MIO SPI pins as GPIO on DAPHNE.

This script is intended to run on the board under sudo/root. It can:
  - apply/remove a runtime DT overlay that disables the conflicting PS users
  - claim the target MIO lines through sysfs GPIO
  - set output directions and safe low defaults
  - optionally pulse selected outputs for a simple smoke test
  - print status for the selected mezzanine pins
"""

from __future__ import annotations

import argparse
import errno
import os
import subprocess
import sys
import time
from pathlib import Path


GPIO_SYSFS = Path("/sys/class/gpio")
OVERLAY_ROOT = Path("/sys/kernel/config/device-tree/overlays")
OVERLAY_NAME = "daphne_psspi_test"
DT_BASE = Path("/sys/firmware/devicetree/base")
TMP_DTS = Path("/tmp/daphne_psspi_disable.dtso")
TMP_DTBO = Path("/tmp/daphne_psspi_disable.dtbo")

MEZZ_PINS = {
    "MEZ0": {"CS": 38, "SCLK": 39, "SDO": 40, "SDI": 50},
    "MEZ1": {"CS": 41, "SCLK": 42, "SDO": 43, "SDI": 61},
    "MEZ2": {"CS": 62, "SCLK": 63, "SDO": 73, "SDI": 74},
    "MEZ3": {"CS": 69, "SCLK": 68, "SDO": 67, "SDI": 57},
    "MEZ4": {"CS": 65, "SCLK": 64, "SDO": 46, "SDI": 45},
}

OUTPUT_ROLES = ("CS", "SCLK", "SDO")
INPUT_ROLES = ("SDI",)

CONFLICT_NODES = [
    "/axi/ethernet@ff0c0000",
    "/axi/usb@ff9d0000",
    "/axi/usb@ff9d0000/usb@fe200000",
    "/axi/usb@ff9e0000",
    "/axi/usb@ff9e0000/usb@fe300000",
]


def ensure_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("run this script under sudo/root")


def selected_mezzes(names: list[str]) -> list[str]:
    if not names:
        return list(MEZZ_PINS.keys())
    return names


def overlay_source() -> str:
    lines = ["/dts-v1/;", "/plugin/;", "", "/ {"]
    for index, node_path in enumerate(CONFLICT_NODES):
        lines.extend(
            [
                f"    fragment@{index} {{",
                f'        target-path = "{node_path}";',
                "        __overlay__ {",
                '            status = "disabled";',
                "        };",
                "    };",
                "",
            ]
        )
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def overlay_dir() -> Path:
    return OVERLAY_ROOT / OVERLAY_NAME


def overlay_active() -> bool:
    return overlay_dir().exists()


def compile_overlay() -> None:
    TMP_DTS.write_text(overlay_source(), encoding="ascii")
    subprocess.run(
        ["dtc", "-@", "-I", "dts", "-O", "dtb", "-o", str(TMP_DTBO), str(TMP_DTS)],
        check=True,
    )


def apply_overlay() -> None:
    if overlay_active():
        return
    compile_overlay()
    overlay_dir().mkdir(parents=True, exist_ok=True)
    try:
        dtbo_path = overlay_dir() / "dtbo"
        dtbo_path.write_bytes(TMP_DTBO.read_bytes())
    except Exception:
        try:
            overlay_dir().rmdir()
        except OSError:
            pass
        raise


def remove_overlay() -> None:
    if not overlay_active():
        return
    overlay_dir().rmdir()


def gpio_path(line: int) -> Path:
    return GPIO_SYSFS / f"gpio{line}"


def export_gpio(line: int) -> None:
    try:
        (GPIO_SYSFS / "export").write_text(f"{line}\n", encoding="ascii")
    except OSError as exc:
        if exc.errno != errno.EBUSY:
            raise


def unexport_gpio(line: int) -> None:
    if not gpio_path(line).exists():
        return
    try:
        (GPIO_SYSFS / "unexport").write_text(f"{line}\n", encoding="ascii")
    except OSError as exc:
        if exc.errno != errno.EINVAL:
            raise


def set_direction(line: int, direction: str) -> None:
    (gpio_path(line) / "direction").write_text(f"{direction}\n", encoding="ascii")


def set_value(line: int, value: int) -> None:
    (gpio_path(line) / "value").write_text(f"{value}\n", encoding="ascii")


def read_value(line: int) -> str:
    return (gpio_path(line) / "value").read_text(encoding="ascii").strip()


def read_direction(line: int) -> str:
    return (gpio_path(line) / "direction").read_text(encoding="ascii").strip()


def claim_mezz(mezz: str) -> None:
    pins = MEZZ_PINS[mezz]
    for role in OUTPUT_ROLES:
        line = pins[role]
        export_gpio(line)
        set_direction(line, "out")
        set_value(line, 0)
    for role in INPUT_ROLES:
        line = pins[role]
        export_gpio(line)
        set_direction(line, "in")


def release_mezz(mezz: str) -> None:
    for line in MEZZ_PINS[mezz].values():
        unexport_gpio(line)


def pulse_line(line: int, count: int, delay_s: float) -> None:
    set_value(line, 0)
    for _ in range(count):
        set_value(line, 1)
        time.sleep(delay_s)
        set_value(line, 0)
        time.sleep(delay_s)


def read_dt_string(node_path: str, prop: str) -> str:
    path = DT_BASE / node_path.lstrip("/") / prop
    if not path.exists():
        return "<missing>"
    raw = path.read_bytes()
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def print_status(mezzes: list[str]) -> None:
    print(f"overlay_active={overlay_active()}")
    for node_path in CONFLICT_NODES:
        print(f"{node_path}: status={read_dt_string(node_path, 'status')}")
    for mezz in mezzes:
        print(f"[{mezz}]")
        for role, line in MEZZ_PINS[mezz].items():
            path = gpio_path(line)
            if path.exists():
                try:
                    direction = read_direction(line)
                    value = read_value(line)
                    state = f"exported direction={direction} value={value}"
                except OSError as exc:
                    state = f"exported unreadable errno={exc.errno} ({exc.strerror})"
            else:
                state = "not-exported"
            print(f"  {role:>4} gpio{line}: {state}")


def do_apply_overlay(_: argparse.Namespace) -> int:
    apply_overlay()
    print_status(list(MEZZ_PINS.keys()))
    return 0


def do_remove_overlay(args: argparse.Namespace) -> int:
    for mezz in selected_mezzes(args.mezz):
        release_mezz(mezz)
    remove_overlay()
    print_status(selected_mezzes(args.mezz))
    return 0


def do_status(args: argparse.Namespace) -> int:
    print_status(selected_mezzes(args.mezz))
    return 0


def do_smoketest(args: argparse.Namespace) -> int:
    mezzes = selected_mezzes(args.mezz)
    apply_overlay()
    for mezz in mezzes:
        claim_mezz(mezz)

    for mezz in mezzes:
        pins = MEZZ_PINS[mezz]
        for role in args.pulse_role:
            pulse_line(pins[role], args.pulse_count, args.pulse_delay_ms / 1000.0)

    print_status(mezzes)

    if not args.keep_lines:
        for mezz in mezzes:
            release_mezz(mezz)
    if not args.keep_overlay:
        remove_overlay()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Test reclaimed DAPHNE PS MIO SPI pins as GPIO on-board."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_mezz_arg(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--mezz",
            action="append",
            choices=sorted(MEZZ_PINS.keys()),
            help="Restrict the action to one or more mezzanines. Default: all.",
        )

    apply_parser = sub.add_parser("apply-overlay", help="Apply the runtime disable overlay.")
    apply_parser.set_defaults(func=do_apply_overlay)

    remove_parser = sub.add_parser("remove-overlay", help="Remove the runtime disable overlay.")
    add_mezz_arg(remove_parser)
    remove_parser.set_defaults(func=do_remove_overlay)

    status_parser = sub.add_parser("status", help="Print overlay and GPIO status.")
    add_mezz_arg(status_parser)
    status_parser.set_defaults(func=do_status)

    smoke_parser = sub.add_parser(
        "smoketest",
        help="Apply overlay, claim GPIOs, optionally pulse outputs, print status, then clean up by default.",
    )
    add_mezz_arg(smoke_parser)
    smoke_parser.add_argument(
        "--pulse-role",
        action="append",
        choices=OUTPUT_ROLES,
        default=[],
        help="Output role to pulse during the test. May be repeated.",
    )
    smoke_parser.add_argument(
        "--pulse-count",
        type=int,
        default=4,
        help="Number of high/low pulses for each selected role.",
    )
    smoke_parser.add_argument(
        "--pulse-delay-ms",
        type=float,
        default=25.0,
        help="Delay between pulse edges in milliseconds.",
    )
    smoke_parser.add_argument(
        "--keep-lines",
        action="store_true",
        help="Keep the GPIO lines exported after the test.",
    )
    smoke_parser.add_argument(
        "--keep-overlay",
        action="store_true",
        help="Keep the runtime DT overlay applied after the test.",
    )
    smoke_parser.set_defaults(func=do_smoketest)

    return parser


def main() -> int:
    ensure_root()
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
