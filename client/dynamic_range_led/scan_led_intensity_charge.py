#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None


HERE = Path(__file__).resolve().parent
from scan_runtime import (
    default_led_client_path,
    default_led_config_path,
    inclusive_range,
    infer_tunnel_board,
    parse_channels,
    resolve_led_biases,
    run_acquire,
    run_bias_monitor,
    run_fe_state_readback,
    run_led,
    run_led_stop,
    utc_now_iso,
)

CLIENT_DIR = HERE.parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.append(str(CLIENT_DIR))

from led_charge import (  # type: ignore
    calibrate_windows_from_folder,
    compute_charge,
    load_channel_waves,
    load_charge_windows,
    mean_waveform,
    pedestal_window_for_charge,
    reanchor_charge_window,
    save_charge_windows,
    summarize_charge_vs_pedestal,
)


DEFAULT_CHANNELS = [4, 5, 6, 7, 12, 13, 14, 15, 18, 19, 20, 21]


def analyze_raw_dir(
    raw_dir: Path,
    *,
    channels: list[int],
    n_samples: int,
    windows: dict[int, Any],
    interpret: str,
    max_waves: int,
    clip_negative: bool,
    hist_bins: int,
    target_signal_fraction: float,
) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for ch in channels:
        path = raw_dir / f"channel_{ch}.dat"
        waves = load_channel_waves(path, n_samples, max_waves=max_waves, interpret=interpret)
        win = windows[ch]
        charges = compute_charge(
            waves,
            integrate_start=win.integrate_start,
            integrate_stop=win.integrate_stop,
            baseline_start=win.baseline_start,
            baseline_stop=win.baseline_stop,
            clip_negative=clip_negative,
        )
        ped_start, ped_stop = pedestal_window_for_charge(win, n_samples=n_samples)
        pedestal_charges = compute_charge(
            waves,
            integrate_start=ped_start,
            integrate_stop=ped_stop,
            baseline_start=win.baseline_start,
            baseline_stop=win.baseline_stop,
            clip_negative=clip_negative,
        )
        metrics = summarize_charge_vs_pedestal(
            charges,
            pedestal_charges,
            target_signal_fraction=target_signal_fraction,
            threshold_sigma=4.0,
            threshold_quantile=0.995,
        )
        mean_wf = mean_waveform(waves)
        out[int(ch)] = {
            "channel": int(ch),
            "n_waveforms": int(waves.shape[0]),
            "baseline_mean": float(mean_wf[win.baseline_start:win.baseline_stop].mean()),
            "mean_peak_value": float(mean_wf[win.peak_index]),
            "mean_onset_value": float(mean_wf[win.onset_index]),
            "integrate_start": int(win.integrate_start),
            "integrate_stop": int(win.integrate_stop),
            "peak_index": int(win.peak_index),
            "onset_index": int(win.onset_index),
            "pedestal_integrate_start": int(ped_start),
            "pedestal_integrate_stop": int(ped_stop),
            "charge_min": float(np.min(charges)),
            "charge_max": float(np.max(charges)),
            "charge_p50": float(np.percentile(charges, 50)),
            "charge_p90": float(np.percentile(charges, 90)),
            "charge_mean": float(np.mean(charges)),
            "charge_std": float(np.std(charges, ddof=0)),
            "pedestal_charge_p50": float(np.percentile(pedestal_charges, 50)),
            "pedestal_charge_std": float(np.std(pedestal_charges, ddof=0)),
            "charges": charges.tolist(),
            "pedestal_charges": pedestal_charges.tolist(),
            "metrics": metrics,
        }
    return out


def save_histogram_grid(path: Path, analysis: dict[int, dict[str, Any]], *, hist_bins: int, title: str) -> None:
    if plt is None or not analysis:
        return

    channels = sorted(analysis)
    ncols = 3
    nrows = (len(channels) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.0 * ncols, 3.5 * nrows), squeeze=False)
    fig.suptitle(title)

    for idx, ch in enumerate(channels):
        ax = axes[idx // ncols][idx % ncols]
        charges = analysis[ch]["charges"]
        metrics = analysis[ch]["metrics"]
        ax.hist(charges, bins=hist_bins, color="#4C72B0", alpha=0.85)
        thr = metrics.get("threshold_charge")
        if thr is not None:
            ax.axvline(float(thr), color="#C44E52", linestyle="--", linewidth=1.2)
        ax.set_title(
            f"ch{ch} frac={_fmt(metrics.get('signal_fraction'))} snr={_fmt(metrics.get('snr_estimate'))}"
        )
        ax.set_xlabel("Integrated charge")
        ax.set_ylabel("Counts")
        ax.grid(True, alpha=0.2)

    for idx in range(len(channels), nrows * ncols):
        axes[idx // ncols][idx % ncols].axis("off")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def save_calibration_persistence_plot(
    path: Path,
    raw_dir: Path,
    *,
    channels: list[int],
    windows: dict[int, Any],
    n_samples: int,
    max_waves: int,
    interpret: str,
) -> None:
    if plt is None:
        return

    ncols = 3
    nrows = (len(channels) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.0 * ncols, 3.6 * nrows), squeeze=False)
    fig.suptitle("Calibration Persistence With Charge Windows")

    for idx, ch in enumerate(channels):
        ax = axes[idx // ncols][idx % ncols]
        waves = load_channel_waves(raw_dir / f"channel_{ch}.dat", n_samples, max_waves=max_waves, interpret=interpret)
        win = windows[ch]
        show_start = max(0, win.search_start - 16)
        show_stop = min(n_samples, win.search_stop + 16)
        xs = np.tile(np.arange(show_start, show_stop), waves.shape[0])
        ys = waves[:, show_start:show_stop].ravel()
        ax.hist2d(xs, ys, bins=[max(32, show_stop - show_start), 120], cmap="viridis")
        ax.axvspan(win.integrate_start, win.integrate_stop, color="#C44E52", alpha=0.20)
        ped_start, ped_stop = pedestal_window_for_charge(win, n_samples=n_samples)
        ax.axvspan(ped_start, ped_stop, color="#55A868", alpha=0.15)
        mean_wf = mean_waveform(waves)
        ax.plot(np.arange(show_start, show_stop), mean_wf[show_start:show_stop], color="white", lw=1.0)
        ax.set_title(f"ch{ch} peak={win.peak_index} win={win.integrate_start}:{win.integrate_stop}")
        ax.set_xlabel("Sample")
        ax.set_ylabel("ADC counts")

    for idx in range(len(channels), nrows * ncols):
        axes[idx // ncols][idx % ncols].axis("off")

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _fmt(value: Any) -> str:
    if value is None:
        return "nan"
    try:
        return f"{float(value):.2f}"
    except Exception:
        return str(value)


def choose_best_by_channel(point_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in point_rows:
        grouped.setdefault(int(row["channel"]), []).append(row)

    out: list[dict[str, Any]] = []
    for ch, rows in sorted(grouped.items()):
        valid = [row for row in rows if row.get("signal_fraction") is not None]
        if not valid:
            continue
        best = min(
            valid,
            key=lambda row: (
                float(row.get("balance_error", 1e9)),
                -float(row.get("snr_estimate") if row.get("snr_estimate") is not None else -1e9),
            ),
        )
        out.append(best)
    return out


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Scan LED intensity with a bright-run fixed integration window and build per-channel charge histograms."
    )
    ap.add_argument("--output-dir", default="client/dynamic_range_led/runs/led_intensity_charge_scan")
    ap.add_argument("--channels", default=",".join(str(ch) for ch in DEFAULT_CHANNELS))
    ap.add_argument("-ip", "--ip", "--host", dest="host", default="127.0.0.1")
    ap.add_argument("-port", "--port", dest="port", type=int, default=9876)
    ap.add_argument("--route", default="mezz/0")
    ap.add_argument("--waveforms", type=int, default=512, help="Waveforms per intensity point")
    ap.add_argument("--calibration-waveforms", type=int, default=128, help="Waveforms for the bright calibration capture")
    ap.add_argument("--waveform-len", type=int, default=2048)
    ap.add_argument("--timeout-ms", type=int, default=30000)
    ap.add_argument("--software-trigger", action="store_true")
    ap.add_argument("--scan-wavelength", choices=["270", "367"], default="270")
    ap.add_argument("--intensity-start", type=int, default=50)
    ap.add_argument("--intensity-stop", type=int, default=2000)
    ap.add_argument("--intensity-step", type=int, default=50)
    ap.add_argument("--calibration-intensity", type=int, default=1500, help="Bright LED point used only to define fixed windows")
    ap.add_argument("--target-signal-fraction", type=float, default=0.5)
    ap.add_argument("--led-client", default=default_led_client_path("ssp_led_run"))
    ap.add_argument("--led-stop-client", default=default_led_client_path("ssp_led_stop"))
    ap.add_argument("--led-config", default=default_led_config_path())
    ap.add_argument("--led-host", default="127.0.0.1")
    ap.add_argument("--led-port", type=int, default=55001)
    ap.add_argument("--led-ssh-tunnel", default="")
    ap.add_argument("--led-ssh-tunnel-remote-host", default="10.73.137.61")
    ap.add_argument("--led-ssh-tunnel-remote-port", type=int, default=55002)
    ap.add_argument("--led-timeout-s", type=float, default=5.0)
    ap.add_argument("--led-channel-mask", type=lambda x: int(str(x), 0), default=1)
    ap.add_argument("--led-number-channels", type=int, default=12)
    ap.add_argument("--pulse-width-ticks", type=int, default=1)
    ap.add_argument("--fixed-bias-270nm", type=int, default=0)
    ap.add_argument("--fixed-bias-367nm", type=int, default=0)
    ap.add_argument("--settle-s", type=float, default=0.5)
    ap.add_argument("--bias-monitor-afes", default="0,1,2,3,4")
    ap.add_argument("--bias-monitor-board", default="", help="Tunnel board for bias monitor wrapper, e.g. daphne-13. Defaults to inferring from --port.")
    ap.add_argument("--bias-monitor-timeout-ms", type=int, default=4000)
    ap.add_argument("--charge-windows-json", default="", help="Use an existing window file and skip the calibration capture")
    ap.add_argument("--charge-baseline-start", type=int, default=0)
    ap.add_argument("--charge-baseline-stop", type=int, default=100)
    ap.add_argument("--charge-search-start", type=int, default=96)
    ap.add_argument("--charge-search-stop", type=int, default=220)
    ap.add_argument("--charge-onset-fraction", type=float, default=0.2)
    ap.add_argument("--charge-window-anchor", choices=["onset", "peak"], default="peak")
    ap.add_argument("--charge-pre-samples", type=int, default=4)
    ap.add_argument("--charge-post-samples", type=int, default=12)
    ap.add_argument("--charge-window-offset", type=int, default=0, help="Legacy onset-based offset; ignored when using peak/onset anchor pre/post samples")
    ap.add_argument("--charge-window-len", type=int, default=24, help="Legacy onset-based length used only during initial pulse finding")
    ap.add_argument("--charge-clip-negative", action="store_true")
    ap.add_argument("--charge-hist-bins", type=int, default=120)
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed")
    ap.add_argument("--skip-fe-readback", action="store_true", help="Skip readback of the current DAPHNE FE state into run metadata.")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    args.channels = parse_channels(args.channels)
    args.bias_monitor_afes = parse_channels(args.bias_monitor_afes)
    intensity_values = inclusive_range(args.intensity_start, args.intensity_stop, args.intensity_step)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    points_dir = output_dir / "points"
    points_dir.mkdir(exist_ok=True)

    manifest = {
        "created_utc": utc_now_iso(),
        "host": args.host,
        "port": args.port,
        "route": args.route,
        "channels": args.channels,
        "waveforms": args.waveforms,
        "calibration_waveforms": args.calibration_waveforms,
        "waveform_len": args.waveform_len,
        "intensity_values": intensity_values,
        "scan_wavelength": args.scan_wavelength,
        "calibration_intensity": args.calibration_intensity,
        "target_signal_fraction": args.target_signal_fraction,
        "pulse_width_ticks": args.pulse_width_ticks,
        "led_channel_mask": args.led_channel_mask,
        "led_ssh_tunnel": args.led_ssh_tunnel,
        "led_ssh_tunnel_remote_host": args.led_ssh_tunnel_remote_host,
        "led_ssh_tunnel_remote_port": args.led_ssh_tunnel_remote_port,
        "bias_monitor_afes": args.bias_monitor_afes,
        "bias_monitor_board": args.bias_monitor_board or infer_tunnel_board(args.port),
        "bias_monitor_timeout_ms": args.bias_monitor_timeout_ms,
        "charge_window_anchor": args.charge_window_anchor,
        "charge_pre_samples": args.charge_pre_samples,
        "charge_post_samples": args.charge_post_samples,
        "charge_window_len_legacy": args.charge_window_len,
        "charge_window_offset_legacy": args.charge_window_offset,
        "charge_baseline_start": args.charge_baseline_start,
        "charge_baseline_stop": args.charge_baseline_stop,
        "charge_search_start": args.charge_search_start,
        "charge_search_stop": args.charge_search_stop,
        "dry_run": args.dry_run,
    }
    if args.skip_fe_readback:
        manifest["fe_state_readback"] = {"skipped": True}
    else:
        manifest["fe_state_readback"] = run_fe_state_readback(
            host=args.host,
            port=args.port,
            route=args.route,
            timeout_ms=args.timeout_ms,
            log_path=output_dir / "fe_state_readback.log",
            json_path=output_dir / "fe_state_readback.json",
            dry_run=args.dry_run,
        )
    (output_dir / "scan_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.charge_windows_json:
        windows = load_charge_windows(args.charge_windows_json)
        windows = {
            ch: reanchor_charge_window(
                windows[ch],
                n_samples=args.waveform_len,
                anchor=args.charge_window_anchor,
                pre_samples=args.charge_pre_samples,
                post_samples=args.charge_post_samples,
            )
            for ch in args.channels
        }
    else:
        cal_dir = output_dir / "calibration"
        cal_raw = cal_dir / "raw"
        cal_dir.mkdir(exist_ok=True)
        cal_raw.mkdir(exist_ok=True)
        cal_meta: dict[str, Any] = {
            "created_utc": utc_now_iso(),
            "type": "calibration",
            "intensity": int(args.calibration_intensity),
            "scan_wavelength": args.scan_wavelength,
            "fe_state_readback_json": str(output_dir / "fe_state_readback.json"),
            "bias_monitor": [],
            "status": "started",
        }
        led_biases = resolve_led_biases(
            scan_wavelength=args.scan_wavelength,
            intensity=args.calibration_intensity,
            fixed_bias_270nm=args.fixed_bias_270nm,
            fixed_bias_367nm=args.fixed_bias_367nm,
        )
        led_info = run_led(
            led_client=args.led_client,
            led_config=args.led_config,
            led_host=args.led_host,
            led_port=args.led_port,
            led_ssh_tunnel=args.led_ssh_tunnel,
            led_ssh_tunnel_remote_host=args.led_ssh_tunnel_remote_host,
            led_ssh_tunnel_remote_port=args.led_ssh_tunnel_remote_port,
            led_timeout_s=args.led_timeout_s,
            led_channel_mask=args.led_channel_mask,
            led_number_channels=args.led_number_channels,
            led_pulse_width_ticks=args.pulse_width_ticks,
            led_intensity_270nm=led_biases["pulse_bias_percent_270nm"],
            led_intensity_367nm=led_biases["pulse_bias_percent_367nm"],
            log_path=cal_dir / "led.log",
            dry_run=args.dry_run,
        )
        cal_meta["led_biases"] = led_biases
        cal_meta["led_start"] = led_info
        cal_meta["led_returncode"] = int(led_info["returncode"])
        if led_info["returncode"] != 0:
            cal_meta["status"] = "led_failed"
            (cal_dir / "metadata.json").write_text(json.dumps(cal_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("Calibration LED command failed", file=sys.stderr)
            return 1
        if not args.dry_run and args.settle_s > 0:
            time.sleep(args.settle_s)
        for afe in args.bias_monitor_afes:
            cal_meta["bias_monitor"].append(
                run_bias_monitor(
                    host=args.host,
                    port=args.port,
                    afe=afe,
                    timeout_ms=args.bias_monitor_timeout_ms,
                    log_path=cal_dir / f"bias_monitor_afe{afe}.log",
                    dry_run=args.dry_run,
                    board=args.bias_monitor_board or infer_tunnel_board(args.port),
                )
            )
        rc_acq, _ = run_acquire(
            host=args.host,
            port=args.port,
            route=args.route,
            raw_dir=cal_raw,
            channels=args.channels,
            waveforms=args.calibration_waveforms,
            waveform_len=args.waveform_len,
            timeout_ms=args.timeout_ms,
            software_trigger=args.software_trigger,
            log_path=cal_dir / "acquire.log",
            dry_run=args.dry_run,
        )
        cal_meta["acquire_returncode"] = int(rc_acq)
        if rc_acq != 0:
            cal_meta["status"] = "acquire_failed"
            (cal_dir / "metadata.json").write_text(json.dumps(cal_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("Calibration acquire failed", file=sys.stderr)
            return 1
        if args.dry_run:
            windows = {}
            cal_meta["status"] = "dry_run"
        else:
            windows = calibrate_windows_from_folder(
                cal_raw,
                channels=args.channels,
                n_samples=args.waveform_len,
                baseline_start=args.charge_baseline_start,
                baseline_stop=args.charge_baseline_stop,
                search_start=args.charge_search_start,
                search_stop=args.charge_search_stop,
                onset_fraction=args.charge_onset_fraction,
                integrate_offset=args.charge_window_offset,
                integrate_len=args.charge_window_len,
                max_waves=args.calibration_waveforms,
                interpret=args.interpret,
            )
            windows = {
                ch: reanchor_charge_window(
                    windows[ch],
                    n_samples=args.waveform_len,
                    anchor=args.charge_window_anchor,
                    pre_samples=args.charge_pre_samples,
                    post_samples=args.charge_post_samples,
                )
                for ch in args.channels
            }
            save_charge_windows(
                cal_dir / "charge_windows.json",
                windows,
                metadata={
                    "created_utc": utc_now_iso(),
                    "source": str(cal_raw),
                    "led_biases": led_biases,
                },
            )
            with (cal_dir / "charge_windows_summary.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "channel",
                        "baseline_start",
                        "baseline_stop",
                        "search_start",
                        "search_stop",
                        "onset_index",
                        "peak_index",
                        "integrate_start",
                        "integrate_stop",
                    ],
                )
                writer.writeheader()
                for ch in args.channels:
                    writer.writerow(windows[ch].as_dict())
            save_calibration_persistence_plot(
                cal_dir / "calibration_persistence_windows.png",
                cal_raw,
                channels=args.channels,
                windows=windows,
                n_samples=args.waveform_len,
                max_waves=args.calibration_waveforms,
                interpret=args.interpret,
            )
            cal_meta["status"] = "calibrated"
            cal_meta["charge_windows_json"] = str(cal_dir / "charge_windows.json")
        (cal_dir / "metadata.json").write_text(json.dumps(cal_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    point_rows: list[dict[str, Any]] = []
    for intensity in intensity_values:
        point_dir = points_dir / f"intensity_{intensity:04d}"
        raw_dir = point_dir / "raw"
        point_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(exist_ok=True)
        point_meta: dict[str, Any] = {
            "created_utc": utc_now_iso(),
            "type": "scan_point",
            "intensity": int(intensity),
            "scan_wavelength": args.scan_wavelength,
            "fe_state_readback_json": str(output_dir / "fe_state_readback.json"),
            "bias_monitor": [],
            "status": "started",
        }

        led_biases = resolve_led_biases(
            scan_wavelength=args.scan_wavelength,
            intensity=intensity,
            fixed_bias_270nm=args.fixed_bias_270nm,
            fixed_bias_367nm=args.fixed_bias_367nm,
        )
        led_info = run_led(
            led_client=args.led_client,
            led_config=args.led_config,
            led_host=args.led_host,
            led_port=args.led_port,
            led_ssh_tunnel=args.led_ssh_tunnel,
            led_ssh_tunnel_remote_host=args.led_ssh_tunnel_remote_host,
            led_ssh_tunnel_remote_port=args.led_ssh_tunnel_remote_port,
            led_timeout_s=args.led_timeout_s,
            led_channel_mask=args.led_channel_mask,
            led_number_channels=args.led_number_channels,
            led_pulse_width_ticks=args.pulse_width_ticks,
            led_intensity_270nm=led_biases["pulse_bias_percent_270nm"],
            led_intensity_367nm=led_biases["pulse_bias_percent_367nm"],
            log_path=point_dir / "led.log",
            dry_run=args.dry_run,
        )
        point_meta["led_biases"] = led_biases
        point_meta["led_start"] = led_info
        point_meta["led_returncode"] = int(led_info["returncode"])
        if led_info["returncode"] != 0:
            point_meta["status"] = "led_failed"
            (point_dir / "metadata.json").write_text(json.dumps(point_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            continue
        if not args.dry_run and args.settle_s > 0:
            time.sleep(args.settle_s)
        for afe in args.bias_monitor_afes:
            point_meta["bias_monitor"].append(
                run_bias_monitor(
                    host=args.host,
                    port=args.port,
                    afe=afe,
                    timeout_ms=args.bias_monitor_timeout_ms,
                    log_path=point_dir / f"bias_monitor_afe{afe}.log",
                    dry_run=args.dry_run,
                    board=args.bias_monitor_board or infer_tunnel_board(args.port),
                )
            )
        rc_acq, acquire_cmd = run_acquire(
            host=args.host,
            port=args.port,
            route=args.route,
            raw_dir=raw_dir,
            channels=args.channels,
            waveforms=args.waveforms,
            waveform_len=args.waveform_len,
            timeout_ms=args.timeout_ms,
            software_trigger=args.software_trigger,
            log_path=point_dir / "acquire.log",
            dry_run=args.dry_run,
        )
        point_meta["acquire_returncode"] = int(rc_acq)
        point_meta["acquire_command"] = acquire_cmd
        if rc_acq != 0:
            point_meta["status"] = "acquire_failed"
            (point_dir / "metadata.json").write_text(json.dumps(point_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            continue
        if args.dry_run:
            point_meta["status"] = "dry_run"
            (point_dir / "metadata.json").write_text(json.dumps(point_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            continue

        analysis = analyze_raw_dir(
            raw_dir,
            channels=args.channels,
            n_samples=args.waveform_len,
            windows=windows,
            interpret=args.interpret,
            max_waves=args.waveforms,
            clip_negative=args.charge_clip_negative,
            hist_bins=args.charge_hist_bins,
            target_signal_fraction=args.target_signal_fraction,
        )
        point_payload = {
            "created_utc": utc_now_iso(),
            "intensity": intensity,
            "scan_wavelength": args.scan_wavelength,
            "led_biases": led_biases,
            "analysis": analysis,
        }
        (point_dir / "analysis.json").write_text(json.dumps(point_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        point_meta["status"] = "analyzed"
        point_meta["analysis_json"] = str(point_dir / "analysis.json")
        point_meta["channels"] = args.channels
        (point_dir / "metadata.json").write_text(json.dumps(point_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        save_histogram_grid(
            point_dir / "charge_histograms.png",
            analysis,
            hist_bins=args.charge_hist_bins,
            title=f"{args.scan_wavelength}nm intensity {intensity}",
        )

        for ch in args.channels:
            metrics = analysis[ch]["metrics"]
            point_rows.append(
                {
                    "channel": ch,
                    "intensity": intensity,
                    "scan_wavelength": args.scan_wavelength,
                    "signal_fraction": metrics.get("signal_fraction"),
                    "balance_error": metrics.get("balance_error"),
                    "snr_estimate": metrics.get("snr_estimate"),
                    "threshold_charge": metrics.get("threshold_charge"),
                    "integrate_start": analysis[ch]["integrate_start"],
                    "integrate_stop": analysis[ch]["integrate_stop"],
                    "peak_index": analysis[ch]["peak_index"],
                    "onset_index": analysis[ch]["onset_index"],
                    "output_dir": str(point_dir),
                }
            )

    run_led_stop(
        led_stop_client=args.led_stop_client,
        led_host=args.led_host,
        led_port=args.led_port,
        led_ssh_tunnel=args.led_ssh_tunnel,
        led_ssh_tunnel_remote_host=args.led_ssh_tunnel_remote_host,
        led_ssh_tunnel_remote_port=args.led_ssh_tunnel_remote_port,
        led_timeout_s=args.led_timeout_s,
        log_path=output_dir / "led_stop.log",
        dry_run=args.dry_run,
    )

    if point_rows:
        with (output_dir / "summary_by_point.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "channel",
                    "intensity",
                    "scan_wavelength",
                    "signal_fraction",
                    "balance_error",
                    "snr_estimate",
                    "threshold_charge",
                    "integrate_start",
                    "integrate_stop",
                    "peak_index",
                    "onset_index",
                    "output_dir",
                ],
            )
            writer.writeheader()
            writer.writerows(point_rows)

        best_rows = choose_best_by_channel(point_rows)
        with (output_dir / "best_by_channel.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "channel",
                    "intensity",
                    "scan_wavelength",
                    "signal_fraction",
                    "balance_error",
                    "snr_estimate",
                    "threshold_charge",
                    "integrate_start",
                    "integrate_stop",
                    "peak_index",
                    "onset_index",
                    "output_dir",
                ],
            )
            writer.writeheader()
            writer.writerows(best_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
