from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
CLIENT_DIR = HERE.parent
DAPHNE_ROOT = CLIENT_DIR.parent


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_led_client_path(name: str) -> str:
    return str(CLIENT_DIR / name)


def default_led_config_path() -> str:
    return str(DAPHNE_ROOT / "configs" / "led_run_defaults.json")


def parse_channels(expr: str) -> list[int]:
    out: list[int] = []
    for token in expr.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a_str, b_str = token.split("-", 1)
            a = int(a_str)
            b = int(b_str)
            if a > b:
                a, b = b, a
            out.extend(range(a, b + 1))
        else:
            out.append(int(token))
    return sorted(set(out))


def inclusive_range(start: int, stop: int, step: int) -> list[int]:
    if step <= 0:
        raise ValueError("step must be > 0")
    values = list(range(start, stop + 1, step))
    if not values or values[-1] != stop:
        values.append(stop)
    return values


def run_cmd(cmd: list[str], *, log_path: Path, dry_run: bool) -> tuple[int, str]:
    if dry_run:
        text = " ".join(cmd) + "\n"
        log_path.write_text(text, encoding="utf-8")
        return 0, text.strip()

    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    combined = proc.stdout
    if proc.stderr:
        combined += ("\n" if combined else "") + proc.stderr
    log_path.write_text(combined, encoding="utf-8")
    return int(proc.returncode), combined.strip()


def extract_fe_state_json(output: str) -> dict[str, Any]:
    marker = "=== FE STATE SNAPSHOT (read-only) ==="
    marker_idx = output.rfind(marker)
    if marker_idx == -1:
        raise ValueError("FE state readback did not contain snapshot marker")
    json_text = output[marker_idx + len(marker):].strip()
    if not json_text:
        raise ValueError("FE state readback did not contain JSON payload")
    return json.loads(json_text)


def run_fe_state_readback(
    *,
    host: str,
    port: int,
    route: str,
    timeout_ms: int,
    log_path: Path,
    json_path: Path,
    dry_run: bool,
    python_exe: str = sys.executable,
) -> dict[str, Any]:
    cmd = [
        python_exe,
        str(CLIENT_DIR / "read_fe_state_v2.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--route",
        route,
        "--timeout",
        str(timeout_ms),
    ]
    if dry_run:
        log_path.write_text(" ".join(cmd) + "\n", encoding="utf-8")
        return {"command": cmd, "dry_run": True, "json_path": str(json_path)}

    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    combined = proc.stdout
    if proc.stderr:
        combined += ("\n" if combined else "") + proc.stderr
    log_path.write_text(combined, encoding="utf-8")

    payload: dict[str, Any] = {
        "command": cmd,
        "returncode": int(proc.returncode),
        "json_path": str(json_path),
    }
    if proc.returncode == 0:
        try:
            config = extract_fe_state_json(combined)
            json_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            payload["config"] = config
        except Exception as exc:
            payload["parse_error"] = str(exc)
    return payload


def resolve_led_biases(
    *,
    scan_wavelength: str,
    intensity: int,
    fixed_bias_270nm: int,
    fixed_bias_367nm: int,
) -> dict[str, int]:
    return {
        "pulse_bias_percent_270nm": int(intensity) if scan_wavelength == "270" else int(fixed_bias_270nm),
        "pulse_bias_percent_367nm": int(intensity) if scan_wavelength == "367" else int(fixed_bias_367nm),
    }


def run_led(
    *,
    led_config: str,
    led_host: str,
    led_port: int,
    led_ssh_tunnel: str,
    led_ssh_tunnel_remote_host: str,
    led_ssh_tunnel_remote_port: int,
    led_timeout_s: float,
    led_channel_mask: int,
    led_number_channels: int,
    led_pulse_width_ticks: int,
    led_intensity_270nm: int,
    led_intensity_367nm: int,
    log_path: Path,
    dry_run: bool,
    led_client: str = "",
) -> dict[str, Any]:
    cmd = [
        str(Path(led_client or default_led_client_path("ssp_led_run")).expanduser()),
        "--config",
        str(Path(led_config).expanduser()),
        "--host",
        led_host,
        "--port",
        str(led_port),
        "--timeout",
        str(led_timeout_s),
        "--channel-mask",
        str(led_channel_mask),
        "--number-channels",
        str(led_number_channels),
        "--pulse-width-ticks",
        str(led_pulse_width_ticks),
        "--pulse-bias-percent-270nm",
        str(led_intensity_270nm),
        "--pulse-bias-percent-367nm",
        str(led_intensity_367nm),
    ]
    if led_ssh_tunnel:
        cmd.extend(
            [
                "--ssh-tunnel",
                led_ssh_tunnel,
                "--ssh-tunnel-remote-host",
                led_ssh_tunnel_remote_host,
                "--ssh-tunnel-remote-port",
                str(led_ssh_tunnel_remote_port),
            ]
        )
    rc, output = run_cmd(cmd, log_path=log_path, dry_run=dry_run)
    return {
        "command": cmd,
        "returncode": rc,
        "output": output,
    }


def run_led_stop(
    *,
    led_host: str,
    led_port: int,
    led_ssh_tunnel: str,
    led_ssh_tunnel_remote_host: str,
    led_ssh_tunnel_remote_port: int,
    led_timeout_s: float,
    log_path: Path,
    dry_run: bool,
    led_stop_client: str = "",
) -> dict[str, Any]:
    cmd = [
        str(Path(led_stop_client or default_led_client_path("ssp_led_stop")).expanduser()),
        "--host",
        led_host,
        "--port",
        str(led_port),
        "--timeout",
        str(led_timeout_s),
    ]
    if led_ssh_tunnel:
        cmd.extend(
            [
                "--ssh-tunnel",
                led_ssh_tunnel,
                "--ssh-tunnel-remote-host",
                led_ssh_tunnel_remote_host,
                "--ssh-tunnel-remote-port",
                str(led_ssh_tunnel_remote_port),
            ]
        )
    rc, output = run_cmd(cmd, log_path=log_path, dry_run=dry_run)
    return {
        "command": cmd,
        "returncode": rc,
        "output": output,
    }


def infer_tunnel_board(port: int) -> str:
    mapping = {
        40113: "daphne-13",
        40114: "daphne-14",
        40115: "daphne-15",
    }
    return mapping.get(int(port), "")


def run_bias_monitor(
    *,
    host: str,
    port: int,
    afe: int,
    timeout_ms: int,
    log_path: Path,
    dry_run: bool,
    python_exe: str = sys.executable,
    board: str = "",
) -> dict[str, Any]:
    if board:
        cmd = [
            str(DAPHNE_ROOT / "utils" / "run_client_via_tunnel.sh"),
            board,
            str(CLIENT_DIR / "vbias_monitor_once.py"),
            "--afe",
            str(afe),
            "--timeout",
            str(timeout_ms),
        ]
    else:
        cmd = [
            python_exe,
            str(CLIENT_DIR / "vbias_monitor_once.py"),
            "--ip",
            host,
            "--port",
            str(port),
            "--afe",
            str(afe),
            "--timeout",
            str(timeout_ms),
        ]

    rc, output = run_cmd(cmd, log_path=log_path, dry_run=dry_run)
    payload: dict[str, Any] = {
        "afe": int(afe),
        "command": cmd,
        "returncode": rc,
        "output": output,
    }
    if board:
        payload["board"] = board
    return payload


def run_acquire(
    *,
    host: str,
    port: int,
    route: str,
    raw_dir: Path,
    channels: list[int],
    waveforms: int,
    waveform_len: int,
    timeout_ms: int,
    software_trigger: bool,
    dry_run: bool,
    log_path: Path,
    python_exe: str = sys.executable,
) -> tuple[int, list[str]]:
    cmd = [
        python_exe,
        str(CLIENT_DIR / "protobuf_acquire_list_channels.py"),
        "-ip",
        host,
        "-port",
        str(port),
        "--route",
        route,
        "--osc_mode",
        "-foldername",
        str(raw_dir),
        "-channel_list",
        ",".join(str(channel) for channel in channels),
        "-N",
        str(waveforms),
        "-L",
        str(waveform_len),
        "--timeout_ms",
        str(timeout_ms),
    ]
    if software_trigger:
        cmd.append("-software_trigger")
    if dry_run:
        log_path.write_text(" ".join(cmd) + "\n", encoding="utf-8")
        return 0, cmd

    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    combined = proc.stdout
    if proc.stderr:
        combined += ("\n" if combined else "") + proc.stderr
    log_path.write_text(combined, encoding="utf-8")
    return int(proc.returncode), cmd
