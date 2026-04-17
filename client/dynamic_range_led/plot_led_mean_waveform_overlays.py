#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import cm
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
CLIENT_DIR = HERE.parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from led_charge import load_channel_waves, mean_waveform


def preferred_monospace_font() -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono", ".SF NS Mono"):
        if candidate in installed:
            return candidate
    return "monospace"


def configure_style() -> None:
    plt.rcParams.update(
        {
            "figure.figsize": (8.0, 4.8),
            "figure.dpi": 180,
            "savefig.dpi": 220,
            "font.family": preferred_monospace_font(),
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "legend.fontsize": 9,
            "legend.frameon": False,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
        }
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Plot channel-by-channel mean waveform overlays across LED intensities for a scan run."
    )
    ap.add_argument("run_dir", help="Run directory with scan_manifest.json and points/")
    ap.add_argument(
        "--output-dir",
        default="",
        help="Default: <run_dir>/waveform_overlays",
    )
    ap.add_argument(
        "--channels",
        default="",
        help="Comma-separated channels to plot; default from manifest",
    )
    ap.add_argument(
        "--max-waves",
        type=int,
        default=0,
        help="Maximum waveforms to use per point/channel; 0 means all",
    )
    ap.add_argument(
        "--zoom-start",
        type=int,
        default=80,
        help="Start sample for the zoom panel",
    )
    ap.add_argument(
        "--zoom-stop",
        type=int,
        default=240,
        help="Stop sample for the zoom panel",
    )
    return ap.parse_args()


def parse_channels(text: str) -> list[int]:
    return [int(tok.strip()) for tok in text.split(",") if tok.strip()]


def load_manifest(run_dir: Path) -> dict:
    return json.loads((run_dir / "scan_manifest.json").read_text(encoding="utf-8"))


def baseline_subtract(mean_wf: np.ndarray, baseline_start: int, baseline_stop: int) -> np.ndarray:
    baseline = float(np.mean(mean_wf[baseline_start:baseline_stop]))
    return mean_wf - baseline


def collect_means(
    run_dir: Path,
    channels: list[int],
    waveform_len: int,
    baseline_start: int,
    baseline_stop: int,
    max_waves: int,
) -> dict[int, list[tuple[int, np.ndarray]]]:
    out: dict[int, list[tuple[int, np.ndarray]]] = {ch: [] for ch in channels}
    for point_dir in sorted((run_dir / "points").glob("intensity_*")):
        intensity = int(point_dir.name.split("_", 1)[1])
        if not (point_dir / "metadata.json").exists():
            continue
        for ch in channels:
            raw_path = point_dir / "raw" / f"channel_{ch}.dat"
            if not raw_path.exists():
                continue
            waves = load_channel_waves(raw_path, waveform_len, max_waves=max_waves, interpret="signed")
            mean_wf = mean_waveform(waves)
            mean_wf = baseline_subtract(mean_wf, baseline_start, baseline_stop)
            out[ch].append((intensity, mean_wf))
    return out


def plot_channel(
    channel: int,
    series: list[tuple[int, np.ndarray]],
    output_dir: Path,
    zoom_start: int,
    zoom_stop: int,
) -> None:
    samples = np.arange(series[0][1].size)
    cmap = cm.get_cmap("viridis", len(series))
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.4), constrained_layout=True)

    for idx, (intensity, mean_wf) in enumerate(series):
        color = cmap(idx)
        axes[0].plot(samples, mean_wf, color=color, linewidth=1.0, label=f"I={intensity}")
        axes[1].plot(samples, mean_wf, color=color, linewidth=1.0, label=f"I={intensity}")

    axes[0].axhline(0.0, color="#7F7F7F", linewidth=0.8, linestyle="--")
    axes[1].axhline(0.0, color="#7F7F7F", linewidth=0.8, linestyle="--")
    axes[0].set_title(f"Channel {channel} | full waveform")
    axes[1].set_title(f"Channel {channel} | zoom")
    axes[0].set_xlabel("Sample")
    axes[1].set_xlabel("Sample")
    axes[0].set_ylabel("Baseline-subtracted mean [ADC counts]")
    axes[1].set_ylabel("Baseline-subtracted mean [ADC counts]")
    axes[1].set_xlim(zoom_start, zoom_stop)
    axes[0].grid(False)
    axes[1].grid(False)
    axes[1].legend(loc="upper right", ncol=1)

    base = output_dir / f"ch{channel:02d}_mean_waveform_overlay"
    fig.savefig(base.with_suffix(".png"))
    fig.savefig(base.with_suffix(".pdf"))
    plt.close(fig)


def plot_overview(
    grouped: dict[int, list[tuple[int, np.ndarray]]],
    output_dir: Path,
    zoom_start: int,
    zoom_stop: int,
) -> None:
    channels = sorted(grouped)
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.0), constrained_layout=True)
    for ax, ch in zip(axes.flat, channels):
        series = grouped[ch]
        samples = np.arange(series[0][1].size)
        cmap = cm.get_cmap("viridis", len(series))
        for idx, (intensity, mean_wf) in enumerate(series):
            ax.plot(samples, mean_wf, color=cmap(idx), linewidth=1.0, label=f"I={intensity}")
        ax.axhline(0.0, color="#7F7F7F", linewidth=0.8, linestyle="--")
        ax.set_xlim(zoom_start, zoom_stop)
        ax.set_title(f"ch{ch}")
        ax.set_xlabel("Sample")
        ax.set_ylabel("Mean [ADC]")
        ax.grid(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=min(len(labels), 6), frameon=False)
    fig.suptitle("VD mean waveform overlays by LED intensity", fontsize=16, y=1.02)
    base = output_dir / "vd_mean_waveform_overview"
    fig.savefig(base.with_suffix(".png"))
    fig.savefig(base.with_suffix(".pdf"))
    plt.close(fig)


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else run_dir / "waveform_overlays"
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_style()

    manifest = load_manifest(run_dir)
    channels = parse_channels(args.channels) if args.channels else [int(ch) for ch in manifest["channels"]]
    waveform_len = int(manifest["waveform_len"])
    baseline_start = int(manifest.get("charge_baseline_start", 0))
    baseline_stop = int(manifest.get("charge_baseline_stop", 100))

    grouped = collect_means(
        run_dir,
        channels,
        waveform_len,
        baseline_start,
        baseline_stop,
        int(args.max_waves),
    )

    for ch in channels:
        if grouped[ch]:
            plot_channel(ch, grouped[ch], output_dir, int(args.zoom_start), int(args.zoom_stop))

    if grouped:
        plot_overview(grouped, output_dir, int(args.zoom_start), int(args.zoom_stop))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
