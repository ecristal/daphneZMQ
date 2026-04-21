#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

HERE = Path(__file__).resolve().parent
CLIENT_DIR = HERE.parent
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from led_charge import load_channel_waves


@dataclass(frozen=True)
class ChannelWindow:
    channel: int
    baseline_start: int
    baseline_stop: int
    onset_index: int
    peak_index: int
    integrate_start: int
    integrate_stop: int


@dataclass(frozen=True)
class PointRow:
    channel: int
    intensity: int
    point_dir: Path
    sample_sigma: float
    n_waveforms: int
    n_clean_waveforms: int


def preferred_monospace_font() -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono", ".SF NS Mono"):
        if candidate in installed:
            return candidate
    return "monospace"


def configure_style() -> None:
    plt.rcParams.update(
        {
            "figure.figsize": (11.0, 4.6),
            "figure.dpi": 180,
            "savefig.dpi": 220,
            "font.family": preferred_monospace_font(),
            "font.size": 10,
            "axes.labelsize": 11,
            "axes.titlesize": 11,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
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
        description="Plot cleaned and rejected waveform overlays for selected LED scan points."
    )
    ap.add_argument("analysis_dir", help="cpp_snr_scan output directory")
    ap.add_argument(
        "--output-dir",
        default="",
        help="Default: <analysis_dir>/publication_plots",
    )
    ap.add_argument(
        "--points",
        default="",
        help="Comma-separated channel:intensity list. Default uses best_by_channel.csv.",
    )
    ap.add_argument(
        "--max-clean",
        type=int,
        default=96,
        help="Maximum number of clean waveforms to draw per panel.",
    )
    ap.add_argument(
        "--max-reject",
        type=int,
        default=48,
        help="Maximum number of rejected waveforms to draw per panel.",
    )
    ap.add_argument(
        "--zoom-start",
        type=int,
        default=96,
        help="First sample to show.",
    )
    ap.add_argument(
        "--zoom-stop",
        type=int,
        default=240,
        help="Last sample to show.",
    )
    ap.add_argument(
        "--pre-pulse-reject-sigma",
        type=float,
        default=5.0,
        help="Baseline activity veto in units of sample_sigma.",
    )
    ap.add_argument(
        "--peak-window-pre",
        type=int,
        default=-1,
        help="Allowed samples before the reference peak.",
    )
    ap.add_argument(
        "--peak-window-post",
        type=int,
        default=-1,
        help="Allowed samples after the reference peak.",
    )
    ap.add_argument(
        "--post-peak-offset",
        type=int,
        default=8,
        help="Offset used to start the late-activity region.",
    )
    ap.add_argument(
        "--pre-activity-frac",
        type=float,
        default=-1.0,
        help="Optional pre-activity fraction veto.",
    )
    ap.add_argument(
        "--pre-activity-floor",
        type=float,
        default=-1.0,
        help="Optional pre-activity absolute veto in ADC counts.",
    )
    ap.add_argument(
        "--post-activity-frac",
        type=float,
        default=-1.0,
        help="Optional late-activity fraction veto.",
    )
    ap.add_argument(
        "--post-activity-floor",
        type=float,
        default=-1.0,
        help="Optional late-activity absolute veto in ADC counts.",
    )
    return ap.parse_args()


def parse_points(text: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        channel_text, intensity_text = token.split(":", 1)
        out.append((int(channel_text), int(intensity_text)))
    return out


def load_windows(path: Path) -> dict[int, ChannelWindow]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, ChannelWindow] = {}
    for key, value in raw.items():
        channel = int(value.get("channel", key))
        out[channel] = ChannelWindow(
            channel=channel,
            baseline_start=int(value["baseline_start"]),
            baseline_stop=int(value["baseline_stop"]),
            onset_index=int(value["onset_index"]),
            peak_index=int(value["peak_index"]),
            integrate_start=int(value["integrate_start"]),
            integrate_stop=int(value["integrate_stop"]),
        )
    return out


def read_rows(path: Path) -> list[PointRow]:
    rows: list[PointRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rows.append(
                PointRow(
                    channel=int(row["channel"]),
                    intensity=int(row["intensity"]),
                    point_dir=Path(row["point_dir"]).resolve(),
                    sample_sigma=float(row["sample_sigma"]),
                    n_waveforms=int(row["n_waveforms"]),
                    n_clean_waveforms=int(row["n_clean_waveforms"]),
                )
            )
    return rows


def pick_rows(analysis_dir: Path, point_keys: list[tuple[int, int]]) -> list[PointRow]:
    summary_rows = read_rows(analysis_dir / "summary_by_point_channel.csv")
    if point_keys:
        lookup = {(row.channel, row.intensity): row for row in summary_rows}
        return [lookup[key] for key in point_keys]
    return read_rows(analysis_dir / "best_by_channel.csv")


def load_waveform_len(run_dir: Path) -> int:
    manifest = json.loads((run_dir / "scan_manifest.json").read_text(encoding="utf-8"))
    return int(manifest["waveform_len"])


def activity_cut_enabled(frac: float, floor: float) -> bool:
    return frac >= 0.0 or floor >= 0.0


def exceeds_activity_cut(value: np.ndarray, peak_amp: np.ndarray, frac: float, floor: float) -> np.ndarray:
    if not activity_cut_enabled(frac, floor):
        return np.zeros_like(value, dtype=bool)
    above_frac = (frac >= 0.0) & (value > frac * np.maximum(peak_amp, 1.0))
    above_floor = (floor >= 0.0) & (value > floor)
    if frac >= 0.0 and floor >= 0.0:
        return above_frac & above_floor
    return above_frac if frac >= 0.0 else above_floor


def evaluate_cuts(
    waves: np.ndarray,
    window: ChannelWindow,
    sample_sigma: float,
    pre_pulse_reject_sigma: float,
    peak_window_pre: int,
    peak_window_post: int,
    post_peak_offset: int,
    pre_activity_frac: float,
    pre_activity_floor: float,
    post_activity_frac: float,
    post_activity_floor: float,
) -> tuple[np.ndarray, np.ndarray]:
    baseline = np.median(waves[:, window.baseline_start:window.baseline_stop], axis=1)
    signal = waves.astype(np.float64, copy=False) - baseline[:, None]

    baseline_max = np.max(np.abs(signal[:, window.baseline_start:window.baseline_stop]), axis=1)
    threshold = pre_pulse_reject_sigma * sample_sigma
    reject_baseline = baseline_max >= threshold

    search_start = max(window.baseline_stop, window.integrate_start - 32)
    search_stop = max(search_start + 1, min(signal.shape[1], max(window.integrate_stop + 64, window.peak_index + max(peak_window_post, post_peak_offset) + 16)))
    peak_idx = np.argmax(signal[:, search_start:search_stop], axis=1) + search_start
    peak_amp = signal[np.arange(signal.shape[0]), peak_idx]

    reject_peak = np.zeros(signal.shape[0], dtype=bool)
    if peak_window_pre >= 0:
        reject_peak |= peak_idx < (window.peak_index - peak_window_pre)
    if peak_window_post >= 0:
        reject_peak |= peak_idx > (window.peak_index + peak_window_post)

    early = signal[:, window.baseline_stop:window.integrate_start]
    early_max = np.max(early, axis=1) if early.shape[1] else np.zeros(signal.shape[0], dtype=np.float64)

    late_max = np.zeros(signal.shape[0], dtype=np.float64)
    for i in range(signal.shape[0]):
        late_start = min(search_stop, max(window.integrate_stop, int(peak_idx[i]) + max(0, post_peak_offset)))
        if late_start < search_stop:
            late_max[i] = np.max(signal[i, late_start:search_stop])

    reject_pre = exceeds_activity_cut(early_max, peak_amp, pre_activity_frac, pre_activity_floor)
    reject_post = exceeds_activity_cut(late_max, peak_amp, post_activity_frac, post_activity_floor)
    clean = ~(reject_baseline | reject_peak | reject_pre | reject_post)
    return signal, clean


def choose_indices(mask: np.ndarray, limit: int) -> np.ndarray:
    idx = np.flatnonzero(mask)
    if limit <= 0 or idx.size <= limit:
        return idx
    sel = np.linspace(0, idx.size - 1, limit, dtype=int)
    return idx[sel]


def plot_single_point(
    row: PointRow,
    window: ChannelWindow,
    waveform_len: int,
    args: argparse.Namespace,
    output_dir: Path,
) -> None:
    raw_path = row.point_dir / "raw" / f"channel_{row.channel}.dat"
    waves = load_channel_waves(raw_path, waveform_len, interpret="signed")
    signal, clean_mask = evaluate_cuts(
        waves,
        window,
        sample_sigma=row.sample_sigma,
        pre_pulse_reject_sigma=float(args.pre_pulse_reject_sigma),
        peak_window_pre=int(args.peak_window_pre),
        peak_window_post=int(args.peak_window_post),
        post_peak_offset=int(args.post_peak_offset),
        pre_activity_frac=float(args.pre_activity_frac),
        pre_activity_floor=float(args.pre_activity_floor),
        post_activity_frac=float(args.post_activity_frac),
        post_activity_floor=float(args.post_activity_floor),
    )
    reject_mask = ~clean_mask
    clean_idx = choose_indices(clean_mask, int(args.max_clean))
    reject_idx = choose_indices(reject_mask, int(args.max_reject))

    samples = np.arange(signal.shape[1])
    zoom_start = max(0, int(args.zoom_start))
    zoom_stop = min(signal.shape[1], int(args.zoom_stop))

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.4), constrained_layout=True, sharey=True)
    panels = [
        (axes[0], clean_idx, "#4C72B0", "#1B4F8C", f"clean {int(clean_mask.sum())}/{signal.shape[0]}"),
        (axes[1], reject_idx, "#C44E52", "#8F2E34", f"rejected {int(reject_mask.sum())}/{signal.shape[0]}"),
    ]

    for ax, idx, wave_color, mean_color, title in panels:
        ax.axhline(0.0, color="#7F7F7F", linewidth=0.8, linestyle="--")
        ax.axvspan(window.integrate_start, window.integrate_stop, color="#999999", alpha=0.10, linewidth=0.0)
        if int(args.peak_window_pre) >= 0 or int(args.peak_window_post) >= 0:
            peak_lo = window.peak_index - max(0, int(args.peak_window_pre))
            peak_hi = window.peak_index + max(0, int(args.peak_window_post))
            ax.axvspan(peak_lo, peak_hi, color="#55A868", alpha=0.08, linewidth=0.0)
        for i in idx:
            ax.plot(samples, signal[i], color=wave_color, linewidth=0.45, alpha=0.14)
        if idx.size > 0:
            ax.plot(samples, np.mean(signal[idx], axis=0), color=mean_color, linewidth=1.3, label="mean")
        ax.set_xlim(zoom_start, zoom_stop)
        ax.set_title(title)
        ax.set_xlabel("Sample")
        ax.grid(False)
        ax.legend(loc="upper right")

    axes[0].set_ylabel("Baseline-subtracted ADC")
    fig.suptitle(
        f"ch{row.channel:02d} | I={row.intensity:04d} | clean overlay",
        fontsize=12,
        y=1.02,
    )
    info = (
        f"window [{window.integrate_start}, {window.integrate_stop})"
        f"   peak {window.peak_index}"
        f"   sigma_sample {row.sample_sigma:.2f}"
    )
    fig.text(0.5, 0.01, info, ha="center", va="bottom", fontsize=9)

    base = output_dir / f"ch{row.channel:02d}_intensity_{row.intensity:04d}_waveform_overlay"
    fig.savefig(base.with_suffix(".pdf"))
    plt.close(fig)


def plot_overview(rows: list[PointRow], output_dir: Path) -> None:
    labels = [f"ch{row.channel:02d} I={row.intensity:04d}" for row in rows]
    fig, ax = plt.subplots(figsize=(10.0, 0.55 * max(1, len(labels)) + 1.0), constrained_layout=True)
    ax.axis("off")
    ax.text(
        0.02,
        0.96,
        "Waveform overlay pages saved alongside histogram plots:\n" + "\n".join(labels),
        ha="left",
        va="top",
        fontsize=11,
        family=preferred_monospace_font(),
    )
    fig.savefig((output_dir / "waveform_overlay_index").with_suffix(".pdf"))
    plt.close(fig)


def main() -> int:
    args = parse_args()
    analysis_dir = Path(args.analysis_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else analysis_dir / "publication_plots"
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_style()

    point_keys = parse_points(args.points) if args.points else []
    rows = pick_rows(analysis_dir, point_keys)
    windows = load_windows(analysis_dir / "channel_windows.json")

    waveform_len_cache: dict[Path, int] = {}
    for row in rows:
        run_dir = row.point_dir.parent.parent
        if run_dir not in waveform_len_cache:
            waveform_len_cache[run_dir] = load_waveform_len(run_dir)
        plot_single_point(
            row,
            windows[row.channel],
            waveform_len_cache[run_dir],
            args,
            output_dir,
        )

    if rows:
        plot_overview(rows, output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
