#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
from scan_runtime import (
    CLIENT_DIR,
    DAPHNE_ROOT,
    default_led_client_path,
    default_led_config_path,
    inclusive_range,
    run_acquire,
    run_bias_monitor,
    run_fe_state_readback,
    run_led,
    run_led_stop,
    utc_now_iso,
)

if str(CLIENT_DIR) not in sys.path:
    sys.path.append(str(CLIENT_DIR))
if str(DAPHNE_ROOT) not in sys.path:
    sys.path.append(str(DAPHNE_ROOT))

from configure_fe_min_v2 import make_default_config  # type: ignore
from pds_configure_utils import build_request_from_seed, send_configure_request  # type: ignore


CHANNEL_ORDER = [4, 5, 6, 7, 12, 13, 14, 15, 18, 19, 21]
AFE_IDS = [0, 1, 2, 3, 4]
AFE_BIAS_DAC = [1195, 916, 0, 0, 0]
ADC_RESOLUTION = 0
ADC_OUTPUT_FORMAT = 1
ADC_SB_FIRST = 0
LPF_CUTOFF_CODE = 4
PGA_GAIN_CODE = 0
LNA_GAIN_CODE = 2
LNA_CLAMP_CODE = 0
BOARD_ID = "61"


def load_anchor_offsets(csv_path: Path) -> dict[int, dict[int, int]]:
    anchors: dict[int, dict[int, int]] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            vgain = int(row["vgain"])
            channel = int(row["channel"])
            offset = int(row["closest_offset_to_2000"])
            anchors.setdefault(channel, {})[vgain] = offset
    missing = [channel for channel in CHANNEL_ORDER if channel not in anchors]
    if missing:
        raise ValueError(f"Missing anchor channels in {csv_path}: {missing}")
    return anchors


def interpolate_channel_offset(
    *,
    channel: int,
    vgain: int,
    anchor_offsets: dict[int, dict[int, int]],
    offset_subtract: int,
    offset_min: int,
    offset_max: int,
) -> int:
    points = sorted(anchor_offsets[channel].items())
    vgains = [item[0] for item in points]
    offsets = [item[1] for item in points]
    if vgain <= vgains[0]:
        value = offsets[0]
    elif vgain >= vgains[-1]:
        value = offsets[-1]
    else:
        value = offsets[0]
        for idx in range(len(points) - 1):
            left_vgain, left_offset = points[idx]
            right_vgain, right_offset = points[idx + 1]
            if left_vgain <= vgain <= right_vgain:
                span = right_vgain - left_vgain
                frac = (vgain - left_vgain) / span if span else 0.0
                value = left_offset + frac * (right_offset - left_offset)
                break
    adjusted = int(round(value)) - int(offset_subtract)
    return max(int(offset_min), min(int(offset_max), adjusted))


def build_seed_config(vgain: int, offsets_by_channel: dict[int, int]) -> dict[str, Any]:
    return {
        BOARD_ID: {
            "bias_ctrl": 1300,
            "channel_analog_conf": {
                "ids": CHANNEL_ORDER,
                "gains": [1] * len(CHANNEL_ORDER),
                "offsets": [offsets_by_channel[channel] for channel in CHANNEL_ORDER],
                "trims": [0] * len(CHANNEL_ORDER),
            },
            "afes": {
                "ids": AFE_IDS,
                "attenuators": [vgain] * len(AFE_IDS),
                "v_biases": AFE_BIAS_DAC,
                "adcs": {
                    "resolution": [ADC_RESOLUTION] * len(AFE_IDS),
                    "output_format": [ADC_OUTPUT_FORMAT] * len(AFE_IDS),
                    "SB_first": [ADC_SB_FIRST] * len(AFE_IDS),
                },
                "pgas": {
                    "lpf_cut_frequency": [LPF_CUTOFF_CODE] * len(AFE_IDS),
                    "integrator_disable": [1] * len(AFE_IDS),
                    "gain": [PGA_GAIN_CODE] * len(AFE_IDS),
                },
                "lnas": {
                    "clamp": [LNA_CLAMP_CODE] * len(AFE_IDS),
                    "integrator_disable": [1] * len(AFE_IDS),
                    "gain": [LNA_GAIN_CODE] * len(AFE_IDS),
                },
            },
        }
    }


def make_config_request(
    *,
    host: str,
    timeout_ms: int,
    seed_cfg: dict[str, Any],
) -> Any:
    defaults = make_default_config(
        ip=host,
        slot=int(seed_cfg.get("slot_id", 1)),
        timeout_ms=timeout_ms,
        per_ch_offset=2275,
        vgain=1600,
        lpf_cutoff=LPF_CUTOFF_CODE,
        pga_gain=PGA_GAIN_CODE,
        lna_gain=LNA_GAIN_CODE,
        lna_clamp=LNA_CLAMP_CODE,
    )
    cfg = build_request_from_seed(seed_cfg, defaults, prefer_seed_common=True)
    cfg.daphne_address = host
    cfg.timeout_ms = timeout_ms
    return cfg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Single-command headless LED dynamic-range sweep using per-channel low-baseline offsets."
    )
    parser.add_argument(
        "--anchor-csv",
        default=str(
            (DAPHNE_ROOT / "client" / "dynamic_range_led" / "per_channel_closest_offsets_target_2000_combined.csv")
        ),
        help="CSV with per-channel anchor offsets.",
    )
    parser.add_argument(
        "--output-dir",
        default="client/dynamic_range_led/runs/vgain_sweep_led",
        help="Output directory for the sweep.",
    )
    parser.add_argument("-ip", "--ip", "--host", dest="host", default="127.0.0.1", help="Server IP/host.")
    parser.add_argument("-port", "--port", dest="port", type=int, default=9876, help="Server port.")
    parser.add_argument("--route", default="mezz/0", help="Route for configure requests.")
    parser.add_argument("--vgain-start", type=int, default=500)
    parser.add_argument("--vgain-stop", type=int, default=3000)
    parser.add_argument("--vgain-step", type=int, default=50)
    parser.add_argument(
        "--offset-subtract",
        type=int,
        default=100,
        help="Subtract this many DAC counts from the interpolated target-2000 offsets to force a lower baseline.",
    )
    parser.add_argument("--offset-min", type=int, default=0)
    parser.add_argument("--offset-max", type=int, default=2550)
    parser.add_argument("--waveforms", type=int, default=64)
    parser.add_argument("--waveform-len", type=int, default=2048)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--bias-monitor-timeout-ms", type=int, default=4000)
    parser.add_argument("--settle-s", type=float, default=0.5)
    parser.add_argument("--software-trigger", action="store_true")
    parser.add_argument("--bias-monitor-afes", default="0,1,2,3,4")
    parser.add_argument("--python-exe", default=sys.executable)
    parser.add_argument(
        "--no-led-start",
        action="store_true",
        help="Do not start the SSP LED pulser before the vgain sweep.",
    )
    parser.add_argument("--led-client", default=default_led_client_path("ssp_led_run"))
    parser.add_argument("--led-stop-client", default=default_led_client_path("ssp_led_stop"))
    parser.add_argument("--led-config", default=default_led_config_path())
    parser.add_argument("--led-host", default="127.0.0.1")
    parser.add_argument("--led-port", type=int, default=55001)
    parser.add_argument("--led-timeout-s", type=float, default=5.0)
    parser.add_argument("--led-channel-mask", type=lambda x: int(str(x), 0), default=7)
    parser.add_argument("--led-number-channels", type=int, default=12)
    parser.add_argument("--led-pulse-width-ticks", type=int, default=100)
    parser.add_argument("--led-intensity-270nm", type=int, default=4094)
    parser.add_argument("--led-intensity-367nm", type=int, default=0)
    parser.add_argument("--skip-fe-readback", action="store_true", help="Skip per-point readback of the configured DAPHNE FE state.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    anchor_csv = Path(args.anchor_csv).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    points_dir = output_dir / "points"
    points_dir.mkdir(exist_ok=True)

    anchor_offsets = load_anchor_offsets(anchor_csv)
    afe_monitor_ids = [int(item.strip()) for item in args.bias_monitor_afes.split(",") if item.strip()]
    vgain_values = inclusive_range(args.vgain_start, args.vgain_stop, args.vgain_step)

    manifest = {
        "created_utc": utc_now_iso(),
        "anchor_csv": str(anchor_csv),
        "host": args.host,
        "port": args.port,
        "route": args.route,
        "vgain_values": vgain_values,
        "channels": CHANNEL_ORDER,
        "offset_subtract": args.offset_subtract,
        "offset_min": args.offset_min,
        "offset_max": args.offset_max,
        "waveforms": args.waveforms,
        "waveform_len": args.waveform_len,
        "settle_s": args.settle_s,
        "software_trigger": args.software_trigger,
        "bias_monitor_afes": afe_monitor_ids,
        "led_auto_start": not args.no_led_start,
        "led_settings": {
            "client": args.led_client,
            "stop_client": args.led_stop_client,
            "config": args.led_config,
            "host": args.led_host,
            "port": args.led_port,
            "channel_mask": args.led_channel_mask,
            "number_channels": args.led_number_channels,
            "pulse_width_ticks": args.led_pulse_width_ticks,
            "pulse_bias_percent_270nm": args.led_intensity_270nm,
            "pulse_bias_percent_367nm": args.led_intensity_367nm,
        },
        "fe_state_readback": {"mode": "per_point", "skipped": bool(args.skip_fe_readback)},
        "dry_run": args.dry_run,
        "notes": "No AFE align after configure.",
    }
    (output_dir / "scan_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary_rows: list[dict[str, Any]] = []

    led_started = False
    try:
        if not args.no_led_start:
            led_start_info = run_led(
                led_client=args.led_client,
                led_config=args.led_config,
                led_host=args.led_host,
                led_port=args.led_port,
                led_timeout_s=args.led_timeout_s,
                led_channel_mask=args.led_channel_mask,
                led_number_channels=args.led_number_channels,
                led_pulse_width_ticks=args.led_pulse_width_ticks,
                led_intensity_270nm=args.led_intensity_270nm,
                led_intensity_367nm=args.led_intensity_367nm,
                log_path=output_dir / "led_start.log",
                dry_run=args.dry_run,
            )
            manifest["led_start"] = led_start_info
            (output_dir / "scan_manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if led_start_info["returncode"] != 0:
                raise RuntimeError(f"Failed to start SSP LED: {led_start_info['returncode']}")
            led_started = True
            if not args.dry_run and args.settle_s > 0:
                time.sleep(args.settle_s)

        for vgain in vgain_values:
            offsets_by_channel = {
                channel: interpolate_channel_offset(
                    channel=channel,
                    vgain=vgain,
                    anchor_offsets=anchor_offsets,
                    offset_subtract=args.offset_subtract,
                    offset_min=args.offset_min,
                    offset_max=args.offset_max,
                )
                for channel in CHANNEL_ORDER
            }
            point_name = f"vgain_{vgain:04d}"
            point_dir = points_dir / point_name
            raw_dir = point_dir / "raw"
            point_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(exist_ok=True)

            seed_cfg = build_seed_config(vgain, offsets_by_channel)
            seed_path = point_dir / "config_applied.json"
            seed_path.write_text(json.dumps(seed_cfg, indent=2, sort_keys=False) + "\n", encoding="utf-8")

            point_meta: dict[str, Any] = {
                "created_utc": utc_now_iso(),
                "vgain": vgain,
                "offsets_by_channel": offsets_by_channel,
                "config_applied_json": str(seed_path),
                "fe_state_readback": {},
                "led_start": manifest.get("led_start", {}),
                "configure": {},
                "bias_monitor": [],
                "acquire": {},
                "status": "started",
            }
            (point_dir / "metadata.json").write_text(
                json.dumps(point_meta, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            cfg = make_config_request(host=args.host, timeout_ms=args.timeout_ms, seed_cfg=seed_cfg[BOARD_ID])
            if args.dry_run:
                point_meta["configure"]["dry_run"] = True
                point_meta["configure"]["summary"] = {
                    "host": args.host,
                    "port": args.port,
                    "route": args.route,
                    "timeout_ms": args.timeout_ms,
                }
                configure_ok = True
            else:
                summary = send_configure_request(
                    cfg,
                    host=args.host,
                    port=args.port,
                    route=args.route,
                    timeout_ms=args.timeout_ms,
                    identity=f"client-led-vgain-{vgain}",
                )
                point_meta["configure"]["summary"] = summary
                configure_ok = bool(
                    summary.get("success", False)
                    or (summary.get("configure_response") or {}).get("success", False)
                )
            (point_dir / "configure.json").write_text(
                json.dumps(point_meta["configure"], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            if not configure_ok:
                point_meta["status"] = "configure_failed"
                summary_rows.append(
                    {
                        "vgain": vgain,
                        "status": point_meta["status"],
                        "output_dir": str(point_dir),
                    }
                )
                (point_dir / "metadata.json").write_text(
                    json.dumps(point_meta, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                continue

            if not args.dry_run and args.settle_s > 0:
                time.sleep(args.settle_s)

            if args.skip_fe_readback:
                point_meta["fe_state_readback"] = {"skipped": True}
            else:
                point_meta["fe_state_readback"] = run_fe_state_readback(
                    host=args.host,
                    port=args.port,
                    route=args.route,
                    timeout_ms=args.timeout_ms,
                    log_path=point_dir / "fe_state_readback.log",
                    json_path=point_dir / "fe_state_readback.json",
                    dry_run=args.dry_run,
                    python_exe=args.python_exe,
                )

            for afe in afe_monitor_ids:
                point_meta["bias_monitor"].append(
                    run_bias_monitor(
                        host=args.host,
                        port=args.port,
                        afe=afe,
                        timeout_ms=args.bias_monitor_timeout_ms,
                        log_path=point_dir / f"bias_monitor_afe{afe}.log",
                        dry_run=args.dry_run,
                        python_exe=args.python_exe,
                    )
                )

            acquire_rc, acquire_cmd = run_acquire(
                host=args.host,
                port=args.port,
                route=args.route,
                raw_dir=raw_dir,
                channels=CHANNEL_ORDER,
                waveforms=args.waveforms,
                waveform_len=args.waveform_len,
                timeout_ms=args.timeout_ms,
                software_trigger=args.software_trigger,
                dry_run=args.dry_run,
                log_path=point_dir / "acquire.log",
                python_exe=args.python_exe,
            )
            point_meta["acquire"]["command"] = acquire_cmd
            point_meta["acquire"]["returncode"] = acquire_rc
            point_meta["status"] = "dry_run" if args.dry_run else ("captured" if acquire_rc == 0 else "acquire_failed")

            summary_rows.append(
                {
                    "vgain": vgain,
                    "status": point_meta["status"],
                    "output_dir": str(point_dir),
                    "min_offset": min(offsets_by_channel.values()),
                    "max_offset": max(offsets_by_channel.values()),
                }
            )
            (point_dir / "metadata.json").write_text(
                json.dumps(point_meta, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    finally:
        if led_started:
            manifest["led_stop"] = run_led_stop(
                led_stop_client=args.led_stop_client,
                led_host=args.led_host,
                led_port=args.led_port,
                led_timeout_s=args.led_timeout_s,
                log_path=output_dir / "led_stop.log",
                dry_run=args.dry_run,
            )
            (output_dir / "scan_manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    with (output_dir / "scan_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["vgain", "status", "output_dir", "min_offset", "max_offset"],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
