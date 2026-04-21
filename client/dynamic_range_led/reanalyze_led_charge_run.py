#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks, savgol_filter

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:
    plt = None


HERE = Path(__file__).resolve().parent
CLIENT_DIR = HERE.parent
if str(CLIENT_DIR) not in __import__("sys").path:
    __import__("sys").path.append(str(CLIENT_DIR))

from led_charge import (  # type: ignore
    compute_baseline,
    compute_charge,
    load_channel_waves,
    summarize_charge_vs_pedestal,
)


@dataclass(frozen=True)
class ChannelWindow:
    channel: int
    reference_intensity: int
    baseline_start: int
    baseline_stop: int
    search_start: int
    search_stop: int
    onset_index: int
    peak_index: int
    integrate_start: int
    integrate_stop: int
    threshold: float
    peak_amplitude: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "reference_intensity": self.reference_intensity,
            "baseline_start": self.baseline_start,
            "baseline_stop": self.baseline_stop,
            "search_start": self.search_start,
            "search_stop": self.search_stop,
            "onset_index": self.onset_index,
            "peak_index": self.peak_index,
            "integrate_start": self.integrate_start,
            "integrate_stop": self.integrate_stop,
            "threshold": self.threshold,
            "peak_amplitude": self.peak_amplitude,
        }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Reanalyze an LED intensity run with channel-specific timing windows derived from a bright mean waveform."
    )
    ap.add_argument("run_dir", help="Primary run directory")
    ap.add_argument(
        "--supplement-run-dir",
        action="append",
        default=[],
        help="Additional run directory whose analyzed points can supplement missing intensities",
    )
    ap.add_argument("--output-dir", default="", help="Output directory (default: <run_dir>/reanalysis_full_hist)")
    ap.add_argument("--channels", default="", help="Comma-separated channels; default from scan_manifest.json")
    ap.add_argument("--waveform-len", type=int, default=0, help="Override waveform length; default from scan_manifest.json")
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed")
    ap.add_argument("--reference-intensity", type=int, default=0, help="Use this intensity to derive channel windows; default highest analyzed")
    ap.add_argument("--search-start", type=int, default=80)
    ap.add_argument("--search-stop", type=int, default=220)
    ap.add_argument("--baseline-margin", type=int, default=12, help="Samples left between onset and baseline stop")
    ap.add_argument("--baseline-len", type=int, default=80)
    ap.add_argument("--pre-samples", type=int, default=6)
    ap.add_argument("--post-samples", type=int, default=12)
    ap.add_argument("--threshold-frac", type=float, default=0.03, help="Fraction of peak amplitude used to define waveform support")
    ap.add_argument(
        "--clip-negative",
        dest="clip_negative",
        action="store_true",
        default=True,
        help="Clip negative sample contributions before integrating charge.",
    )
    ap.add_argument(
        "--no-clip-negative",
        dest="clip_negative",
        action="store_false",
        help="Keep negative sample contributions in the integrated charge.",
    )
    ap.add_argument("--hist-bins", type=int, default=320)
    ap.add_argument("--fit-channel", type=int, action="append", default=[15], help="Channel(s) for PE fit attempts")
    ap.add_argument("--fit-intensity", type=int, default=1150, help="Intensity used for PE fit attempts")
    ap.add_argument(
        "--fit-all-points",
        action="store_true",
        help="Run PE fits for every analyzed point/channel pair instead of only --fit-intensity.",
    )
    ap.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="Worker processes for PE fits. Default uses a bounded CPU-based value.",
    )
    ap.add_argument(
        "--gaussian-max-peaks",
        type=int,
        default=8,
        help="Maximum detected peaks to include in the multi-Gaussian ladder fit.",
    )
    ap.add_argument(
        "--vinogradov-nmax",
        type=int,
        default=10,
        help="Maximum PE multiplicity term in the Vinogradov-like sum.",
    )
    return ap.parse_args()


def load_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "scan_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing scan_manifest.json in {run_dir}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def parse_channels_arg(value: str, fallback: list[int]) -> list[int]:
    if not value.strip():
        return list(fallback)
    out: list[int] = []
    for token in value.split(","):
        token = token.strip()
        if token:
            out.append(int(token))
    return out


def gather_analyzed_points(run_dirs: list[Path]) -> dict[int, Path]:
    chosen: dict[int, Path] = {}
    for run_dir in run_dirs:
        points_dir = run_dir / "points"
        if not points_dir.is_dir():
            continue
        for point_dir in sorted(points_dir.iterdir()):
            if not point_dir.is_dir() or not point_dir.name.startswith("intensity_"):
                continue
            meta_path = point_dir / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if meta.get("status") != "analyzed":
                continue
            intensity = int(meta["intensity"])
            # Later run dirs win; this lets supplement dirs patch missing points like the 1750 rerun.
            chosen[intensity] = point_dir
    return dict(sorted(chosen.items()))


def derive_window_from_mean(
    mean_wf: np.ndarray,
    *,
    channel: int,
    reference_intensity: int,
    search_start: int,
    search_stop: int,
    baseline_margin: int,
    baseline_len: int,
    pre_samples: int,
    post_samples: int,
    threshold_frac: float,
) -> ChannelWindow:
    n_samples = int(mean_wf.size)
    s_lo = max(0, min(n_samples - 2, int(search_start)))
    s_hi = max(s_lo + 2, min(n_samples, int(search_stop)))

    rough_base_stop = min(s_lo, max(32, s_lo))
    rough_base = mean_wf[:rough_base_stop]
    rough_baseline = float(np.median(rough_base))
    signal = mean_wf[s_lo:s_hi] - rough_baseline
    if signal.size >= 11:
        smooth = savgol_filter(signal, 11, 3)
    elif signal.size >= 5:
        window = signal.size if signal.size % 2 == 1 else signal.size - 1
        smooth = savgol_filter(signal, max(3, window), 2)
    else:
        smooth = signal

    peak_rel = int(np.argmax(smooth))
    peak_index = s_lo + peak_rel
    peak_amplitude = float(smooth[peak_rel])
    if peak_amplitude <= 0:
        raise ValueError(f"Channel {channel}: could not find a positive pulse in the mean waveform")

    baseline_rms = float(np.std(rough_base - rough_baseline, ddof=0))
    threshold = max(float(threshold_frac) * peak_amplitude, 3.0 * baseline_rms)

    left = peak_rel
    while left > 0 and smooth[left] > threshold:
        left -= 1
    right = peak_rel
    while right < smooth.size - 1 and smooth[right] > threshold:
        right += 1

    onset_index = s_lo + max(0, left)
    return_index = s_lo + min(smooth.size - 1, right)

    baseline_stop = max(16, onset_index - int(baseline_margin))
    baseline_start = max(0, baseline_stop - int(baseline_len))
    integrate_start = max(0, onset_index - int(pre_samples))
    integrate_stop = min(n_samples, return_index + int(post_samples))
    if integrate_stop <= integrate_start:
        integrate_stop = min(n_samples, integrate_start + max(8, int(post_samples)))

    return ChannelWindow(
        channel=int(channel),
        reference_intensity=int(reference_intensity),
        baseline_start=int(baseline_start),
        baseline_stop=int(baseline_stop),
        search_start=int(s_lo),
        search_stop=int(s_hi),
        onset_index=int(onset_index),
        peak_index=int(peak_index),
        integrate_start=int(integrate_start),
        integrate_stop=int(integrate_stop),
        threshold=float(threshold),
        peak_amplitude=float(peak_amplitude),
    )


def analyze_point(
    point_dir: Path,
    *,
    channels: list[int],
    waveform_len: int,
    windows: dict[int, ChannelWindow],
    interpret: str,
    clip_negative: bool,
) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    raw_dir = point_dir / "raw"
    for ch in channels:
        waves = load_channel_waves(raw_dir / f"channel_{ch}.dat", waveform_len, interpret=interpret)
        win = windows[ch]
        charges = compute_charge(
            waves,
            integrate_start=win.integrate_start,
            integrate_stop=win.integrate_stop,
            baseline_start=win.baseline_start,
            baseline_stop=win.baseline_stop,
            clip_negative=clip_negative,
        )
        ped_len = int(win.integrate_stop - win.integrate_start)
        ped_stop = int(win.baseline_stop)
        ped_start = max(int(win.baseline_start), ped_stop - ped_len)
        pedestal = compute_charge(
            waves,
            integrate_start=ped_start,
            integrate_stop=ped_stop,
            baseline_start=win.baseline_start,
            baseline_stop=win.baseline_stop,
            clip_negative=clip_negative,
        )
        metrics = summarize_charge_vs_pedestal(charges, pedestal, target_signal_fraction=0.5)
        baseline_values = compute_baseline(waves, win.baseline_start, win.baseline_stop)
        mean_wf = waves.astype(np.float64, copy=False).mean(axis=0)
        out[ch] = {
            "channel": int(ch),
            "n_waveforms": int(waves.shape[0]),
            "baseline_mean": float(np.mean(baseline_values)),
            "baseline_std": float(np.std(baseline_values, ddof=0)),
            "mean_peak_value": float(mean_wf[win.peak_index]),
            "mean_onset_value": float(mean_wf[win.onset_index]),
            "integrate_start": int(win.integrate_start),
            "integrate_stop": int(win.integrate_stop),
            "baseline_start": int(win.baseline_start),
            "baseline_stop": int(win.baseline_stop),
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
            "pedestal_charge_p50": float(np.percentile(pedestal, 50)),
            "pedestal_charge_std": float(np.std(pedestal, ddof=0)),
            "charges": charges.tolist(),
            "pedestal_charges": pedestal.tolist(),
            "metrics": metrics,
        }
    return out


def save_point_grid(path: Path, point_analysis: dict[int, dict[str, Any]], *, hist_bins: int, title: str) -> None:
    if plt is None:
        return
    channels = sorted(point_analysis)
    ncols = 3
    nrows = (len(channels) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.0 * ncols, 3.6 * nrows), squeeze=False)
    fig.suptitle(title)
    for idx, ch in enumerate(channels):
        ax = axes[idx // ncols][idx % ncols]
        charges = np.asarray(point_analysis[ch]["charges"], dtype=float)
        charges = charges[charges >= 0.0]
        metrics = point_analysis[ch]["metrics"]
        ax.hist(charges, bins=hist_bins, color="#4C72B0", alpha=0.85)
        thr = metrics.get("threshold_charge")
        if thr is not None:
            ax.axvline(float(thr), color="#C44E52", linestyle="--", linewidth=1.0)
        ax.set_xlim(left=0.0)
        ax.set_title(
            f"ch{ch} snr={_fmt(metrics.get('snr_estimate'))} frac={_fmt(metrics.get('signal_fraction'))}"
        )
        ax.set_xlabel("Charge")
        ax.set_ylabel("Counts")
        ax.grid(True, alpha=0.2)
    for idx in range(len(channels), nrows * ncols):
        axes[idx // ncols][idx % ncols].axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_channel_overlay(path: Path, rows: list[dict[str, Any]], *, hist_bins: int, title: str) -> None:
    if plt is None or not rows:
        return
    fig, ax = plt.subplots(figsize=(10, 6))
    cmap = plt.get_cmap("viridis")
    rows = sorted(rows, key=lambda item: int(item["intensity"]))
    for idx, row in enumerate(rows):
        charges = np.asarray(row["charges"], dtype=float)
        charges = charges[charges >= 0.0]
        color = cmap(idx / max(1, len(rows) - 1))
        ax.hist(
            charges,
            bins=hist_bins,
            histtype="step",
            linewidth=1.2,
            alpha=0.9,
            label=f"I={row['intensity']} snr={_fmt(row['snr_estimate'])}",
            color=color,
        )
    ax.set_xlim(left=0.0)
    ax.set_xlabel("Integrated charge")
    ax.set_ylabel("Counts")
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def save_window_plot(path: Path, mean_waveforms: dict[int, np.ndarray], windows: dict[int, ChannelWindow]) -> None:
    if plt is None:
        return
    channels = sorted(mean_waveforms)
    ncols = 3
    nrows = (len(channels) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.0 * ncols, 3.2 * nrows), squeeze=False)
    fig.suptitle("Reference Mean Waveforms and Derived Charge Windows")
    for idx, ch in enumerate(channels):
        ax = axes[idx // ncols][idx % ncols]
        mean_wf = mean_waveforms[ch]
        win = windows[ch]
        xs = np.arange(mean_wf.size)
        ax.plot(xs, mean_wf, color="#4C72B0")
        ax.axvspan(win.baseline_start, win.baseline_stop, color="#55A868", alpha=0.15)
        ax.axvspan(win.integrate_start, win.integrate_stop, color="#C44E52", alpha=0.18)
        ax.axvline(win.peak_index, color="#8172B2", linestyle="--", linewidth=1.0)
        ax.set_title(f"ch{ch} ref I={win.reference_intensity}")
        ax.set_xlabel("Sample")
        ax.set_ylabel("ADC")
        ax.grid(True, alpha=0.2)
    for idx in range(len(channels), nrows * ncols):
        axes[idx // ncols][idx % ncols].axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def gaussian_sum(x: np.ndarray, *params: float) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for idx in range(0, len(params), 3):
        amp, mu, sigma = params[idx : idx + 3]
        sigma = max(1e-6, sigma)
        y += amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)
    return y


def generalized_poisson_pmf(n: int, mu: float, lamb: float) -> float:
    if n == 0:
        return math.exp(-mu)
    inner = mu + lamb * n
    if inner <= 0:
        return 0.0
    return float(mu * (inner ** (n - 1)) * math.exp(-inner) / math.factorial(n))


def vinogradov_like_model(
    x: np.ndarray,
    amplitude: float,
    pedestal: float,
    gain: float,
    sigma0: float,
    sigma1: float,
    mu: float,
    lamb: float,
    *,
    nmax: int = 8,
) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for n in range(nmax + 1):
        weight = generalized_poisson_pmf(n, mu, lamb)
        sigma_n = math.sqrt(max(1e-6, sigma0 * sigma0 + n * sigma1 * sigma1))
        y += weight * np.exp(-0.5 * ((x - (pedestal + n * gain)) / sigma_n) ** 2) / (sigma_n * math.sqrt(2.0 * math.pi))
    return amplitude * y


def attempt_pe_fit(
    charges: np.ndarray,
    *,
    gaussian_max_peaks: int = 8,
    vinogradov_nmax: int = 10,
) -> dict[str, Any]:
    charges = np.asarray(charges, dtype=float)
    charges = charges[charges >= 0.0]
    if charges.size < 100:
        return {"status": "insufficient_data"}

    hi = float(np.quantile(charges, 0.999))
    counts, edges = np.histogram(charges, bins=360, range=(0.0, hi))
    mids = 0.5 * (edges[:-1] + edges[1:])
    if counts.size < 11:
        return {"status": "insufficient_bins"}

    smooth = savgol_filter(counts, 11, 3)
    peaks, props = find_peaks(smooth, prominence=max(3.0, float(np.max(smooth)) * 0.01), distance=8)
    peak_positions = mids[peaks]
    if peak_positions.size < 2:
        return {"status": "no_peak_ladder", "peak_positions": peak_positions.tolist()}

    peak_positions = peak_positions[: max(2, int(gaussian_max_peaks))]
    counts_guess = counts[peaks[: len(peak_positions)]]
    spacing = float(np.median(np.diff(peak_positions)))
    sigma_guess = max(float(np.diff(edges)[0]) * 2.0, spacing / 5.0)

    # Independent Gaussian ladder fit, using as many resolved peaks as remain stable.
    g_init: list[float] = []
    g_lo: list[float] = []
    g_hi: list[float] = []
    for amp, mu in zip(counts_guess, peak_positions):
        g_init.extend([float(max(1.0, amp)), float(mu), float(sigma_guess)])
        g_lo.extend([0.0, float(mu - spacing * 0.4), float(sigma_guess * 0.25)])
        g_hi.extend([float(np.max(counts) * 10.0), float(mu + spacing * 0.4), float(spacing)])

    result: dict[str, Any] = {"status": "ok", "peak_positions": peak_positions.tolist()}
    try:
        g_popt, _ = curve_fit(gaussian_sum, mids, counts, p0=g_init, bounds=(g_lo, g_hi), maxfev=50000)
        result["gaussian_fit"] = {
            "status": "ok",
            "params": [float(v) for v in g_popt],
            "n_gaussians": len(g_popt) // 3,
        }
    except Exception as exc:
        result["gaussian_fit"] = {"status": "failed", "error": str(exc)}

    try:
        pedestal0 = float(peak_positions[0])
        gain0 = float(np.median(np.diff(peak_positions[: min(4, peak_positions.size)])))
        amp0 = float(np.sum(counts) * np.diff(edges)[0])
        v_p0 = [amp0, pedestal0, max(gain0, 1.0), sigma_guess * 0.7, sigma_guess * 0.5, 1.5, 0.1]
        v_lo = [0.0, 0.0, max(1.0, gain0 * 0.5), 1.0, 1.0, 0.01, 0.0]
        v_hi = [amp0 * 10.0, hi, gain0 * 1.5 if gain0 > 0 else hi, spacing, spacing, 8.0, 0.95]
        vinogradov_model = lambda x, amplitude, pedestal, gain, sigma0, sigma1, mu, lamb: vinogradov_like_model(  # noqa: E731
            x,
            amplitude,
            pedestal,
            gain,
            sigma0,
            sigma1,
            mu,
            lamb,
            nmax=max(1, int(vinogradov_nmax)),
        )
        v_popt, _ = curve_fit(vinogradov_model, mids, counts, p0=v_p0, bounds=(v_lo, v_hi), maxfev=50000)
        result["vinogradov_like_fit"] = {
            "status": "ok",
            "nmax": max(1, int(vinogradov_nmax)),
            "params": {
                "amplitude": float(v_popt[0]),
                "pedestal": float(v_popt[1]),
                "gain": float(v_popt[2]),
                "sigma0": float(v_popt[3]),
                "sigma1": float(v_popt[4]),
                "mu": float(v_popt[5]),
                "lambda": float(v_popt[6]),
            },
        }
    except Exception as exc:
        result["vinogradov_like_fit"] = {"status": "failed", "error": str(exc)}

    result["histogram"] = {
        "bin_centers": mids.tolist(),
        "counts": counts.tolist(),
    }
    return result


def save_fit_plot(path: Path, charges: np.ndarray, fit_result: dict[str, Any], *, title: str) -> None:
    if plt is None:
        return
    charges = np.asarray(charges, dtype=float)
    charges = charges[charges >= 0.0]
    hi = float(np.quantile(charges, 0.999))
    counts, edges = np.histogram(charges, bins=360, range=(0.0, hi))
    mids = 0.5 * (edges[:-1] + edges[1:])

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.step(mids, counts, where="mid", color="#4C72B0", label="Histogram")

    g_fit = fit_result.get("gaussian_fit", {})
    if g_fit.get("params"):
        y = gaussian_sum(mids, *g_fit["params"])
        ax.plot(mids, y, color="#C44E52", lw=1.8, label="Multi-Gaussian fit")

    v_fit = fit_result.get("vinogradov_like_fit", {})
    if v_fit.get("status") == "ok":
        p = v_fit["params"]
        y = vinogradov_like_model(
            mids,
            p["amplitude"],
            p["pedestal"],
            p["gain"],
            p["sigma0"],
            p["sigma1"],
            p["mu"],
            p["lambda"],
            nmax=int(v_fit.get("nmax", 8)),
        )
        ax.plot(mids, y, color="#55A868", lw=1.4, label="Vinogradov-like fit")

    ax.set_xlim(left=0.0)
    ax.set_xlabel("Integrated charge")
    ax.set_ylabel("Counts")
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def _fmt(value: Any) -> str:
    if value is None:
        return "nan"
    try:
        return f"{float(value):.3f}"
    except Exception:
        return str(value)


def _default_fit_channels(channels: list[int], requested: list[int], fit_all_points: bool) -> list[int]:
    requested_unique = sorted({int(ch) for ch in requested})
    if fit_all_points and requested_unique == [15] and 15 not in channels:
        return list(channels)
    return [ch for ch in requested_unique if ch in channels]


def _resolve_jobs(requested_jobs: int, n_tasks: int) -> int:
    if n_tasks <= 1:
        return 1
    if requested_jobs > 0:
        return max(1, min(int(requested_jobs), n_tasks))
    cpu_count = os.cpu_count() or 1
    return max(1, min(n_tasks, cpu_count - 1 if cpu_count > 1 else 1))


def _run_fit_task(
    *,
    analysis_json_path: str,
    channel: int,
    intensity: int,
    output_base: str,
    run_name: str,
    gaussian_max_peaks: int,
    vinogradov_nmax: int,
) -> dict[str, Any]:
    analysis_path = Path(analysis_json_path)
    out_base = Path(output_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
        charges = np.asarray(payload["channels"][str(channel)]["charges"], dtype=float)
        fit_result = attempt_pe_fit(
            charges,
            gaussian_max_peaks=gaussian_max_peaks,
            vinogradov_nmax=vinogradov_nmax,
        )
        json_path = out_base.with_suffix(".json")
        png_path = out_base.with_suffix(".png")
        json_path.write_text(json.dumps(fit_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        save_fit_plot(
            png_path,
            charges,
            fit_result,
            title=f"{run_name} ch{channel} intensity={intensity} PE fit",
        )
        gaussian_fit = fit_result.get("gaussian_fit", {})
        vinogradov_fit = fit_result.get("vinogradov_like_fit", {})
        return {
            "channel": int(channel),
            "intensity": int(intensity),
            "analysis_json": str(analysis_path),
            "json_path": str(json_path),
            "png_path": str(png_path),
            "status": str(fit_result.get("status", "ok")),
            "n_detected_peaks": int(len(fit_result.get("peak_positions", []))),
            "gaussian_status": str(gaussian_fit.get("status", "missing")),
            "n_gaussians": int(gaussian_fit.get("n_gaussians", 0)) if gaussian_fit.get("n_gaussians") is not None else 0,
            "vinogradov_status": str(vinogradov_fit.get("status", "missing")),
            "vinogradov_nmax": int(vinogradov_fit.get("nmax", vinogradov_nmax)) if vinogradov_fit else int(vinogradov_nmax),
        }
    except Exception as exc:
        return {
            "channel": int(channel),
            "intensity": int(intensity),
            "analysis_json": str(analysis_path),
            "json_path": str(out_base.with_suffix(".json")),
            "png_path": str(out_base.with_suffix(".png")),
            "status": "fit_task_failed",
            "error": str(exc),
            "n_detected_peaks": 0,
            "gaussian_status": "failed",
            "n_gaussians": 0,
            "vinogradov_status": "failed",
            "vinogradov_nmax": int(vinogradov_nmax),
        }


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    supplement_dirs = [Path(p).expanduser().resolve() for p in args.supplement_run_dir]
    manifest = load_manifest(run_dir)
    channels = parse_channels_arg(args.channels, fallback=[int(ch) for ch in manifest.get("channels", [])])
    waveform_len = int(args.waveform_len or manifest.get("waveform_len", 1024))
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (run_dir / "reanalysis_full_hist")
    output_dir.mkdir(parents=True, exist_ok=True)

    point_dirs = gather_analyzed_points([run_dir, *supplement_dirs])
    if not point_dirs:
        raise RuntimeError(f"No analyzed points found under {run_dir}")

    reference_intensity = int(args.reference_intensity) if args.reference_intensity > 0 else max(point_dirs)
    if reference_intensity not in point_dirs:
        raise RuntimeError(f"Reference intensity {reference_intensity} not available in analyzed points")

    reference_dir = point_dirs[reference_intensity]
    raw_dir = reference_dir / "raw"

    windows: dict[int, ChannelWindow] = {}
    mean_waveforms: dict[int, np.ndarray] = {}
    for ch in channels:
        waves = load_channel_waves(raw_dir / f"channel_{ch}.dat", waveform_len, interpret=args.interpret)
        mean_wf = waves.astype(np.float64, copy=False).mean(axis=0)
        mean_waveforms[ch] = mean_wf
        windows[ch] = derive_window_from_mean(
            mean_wf,
            channel=ch,
            reference_intensity=reference_intensity,
            search_start=args.search_start,
            search_stop=args.search_stop,
            baseline_margin=args.baseline_margin,
            baseline_len=args.baseline_len,
            pre_samples=args.pre_samples,
            post_samples=args.post_samples,
            threshold_frac=args.threshold_frac,
        )

    (output_dir / "channel_windows.json").write_text(
        json.dumps({str(ch): win.as_dict() for ch, win in sorted(windows.items())}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    save_window_plot(output_dir / "channel_windows.png", mean_waveforms, windows)

    per_channel_rows: dict[int, list[dict[str, Any]]] = {ch: [] for ch in channels}
    summary_rows: list[dict[str, Any]] = []
    point_analysis_root = output_dir / "points"
    point_analysis_root.mkdir(exist_ok=True)

    for intensity, point_dir in point_dirs.items():
        analysis_dir = point_analysis_root / point_dir.name
        analysis_dir.mkdir(exist_ok=True)
        point_analysis = analyze_point(
            point_dir,
            channels=channels,
            waveform_len=waveform_len,
            windows=windows,
            interpret=args.interpret,
            clip_negative=bool(args.clip_negative),
        )
        payload = {
            "source_point_dir": str(point_dir),
            "intensity": int(intensity),
            "channels": {str(ch): data for ch, data in sorted(point_analysis.items())},
        }
        (analysis_dir / "analysis.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        save_point_grid(
            analysis_dir / "charge_histograms_full.png",
            point_analysis,
            hist_bins=args.hist_bins,
            title=f"{run_dir.name} intensity={intensity} full charge histograms",
        )
        for ch, data in point_analysis.items():
            metrics = data["metrics"]
            row = {
                "channel": int(ch),
                "intensity": int(intensity),
                "point": point_dir.name,
                "snr_estimate": metrics.get("snr_estimate"),
                "signal_fraction": metrics.get("signal_fraction"),
                "balance_error": metrics.get("balance_error"),
                "threshold_charge": metrics.get("threshold_charge"),
                "baseline_mean": data["baseline_mean"],
                "baseline_std": data["baseline_std"],
                "integrate_start": data["integrate_start"],
                "integrate_stop": data["integrate_stop"],
                "baseline_start": data["baseline_start"],
                "baseline_stop": data["baseline_stop"],
                "peak_index": data["peak_index"],
                "onset_index": data["onset_index"],
                "charge_mean": data["charge_mean"],
                "charge_std": data["charge_std"],
                "pedestal_charge_std": data["pedestal_charge_std"],
            }
            summary_rows.append(row)
            per_channel_rows[ch].append(
                {
                    "intensity": int(intensity),
                    "charges": data["charges"],
                    "snr_estimate": metrics.get("snr_estimate"),
                }
            )

    with (output_dir / "summary_by_point.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    best_rows: list[dict[str, Any]] = []
    for ch in sorted(per_channel_rows):
        save_channel_overlay(
            output_dir / f"channel_{ch:02d}_overlay_hist.png",
            per_channel_rows[ch],
            hist_bins=args.hist_bins,
            title=f"{run_dir.name} ch{ch} full charge histograms",
        )
        candidates = [row for row in summary_rows if int(row["channel"]) == ch]
        reliable = [
            row
            for row in candidates
            if row["snr_estimate"] is not None
            and 0.2 <= float(row["signal_fraction"]) <= 0.8
            and float(row["snr_estimate"]) > 0
        ]
        pool = reliable or [
            row
            for row in candidates
            if row["snr_estimate"] is not None and float(row["snr_estimate"]) > 0
        ]
        if pool:
            best = max(pool, key=lambda row: float(row["snr_estimate"]))
            best_rows.append(best)

    if best_rows:
        with (output_dir / "best_snr_by_channel.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(best_rows[0].keys()))
            writer.writeheader()
            writer.writerows(best_rows)

    fit_dir = output_dir / "pe_fits"
    fit_dir.mkdir(exist_ok=True)
    fit_channels = _default_fit_channels(channels, list(args.fit_channel), bool(args.fit_all_points))
    fit_rows: list[dict[str, Any]] = []
    if args.fit_all_points:
        fit_points = [(int(intensity), point_dir) for intensity, point_dir in point_dirs.items()]
    else:
        selected_point = point_dirs.get(int(args.fit_intensity))
        fit_points = [] if selected_point is None else [(int(args.fit_intensity), selected_point)]

    fit_tasks: list[dict[str, Any]] = []
    for intensity, point_dir in fit_points:
        analysis_path = point_analysis_root / point_dir.name / "analysis.json"
        for ch in fit_channels:
            fit_tasks.append(
                {
                    "analysis_json_path": str(analysis_path),
                    "channel": int(ch),
                    "intensity": int(intensity),
                    "output_base": str(
                        fit_dir / point_dir.name / f"channel_{ch:02d}_intensity_{intensity:04d}"
                    ),
                    "run_name": run_dir.name,
                    "gaussian_max_peaks": int(args.gaussian_max_peaks),
                    "vinogradov_nmax": int(args.vinogradov_nmax),
                }
            )

    fit_jobs = _resolve_jobs(int(args.jobs), len(fit_tasks)) if fit_tasks else 0
    fit_executor = "none"
    if fit_tasks:
        if fit_jobs == 1:
            fit_executor = "serial"
            for task in fit_tasks:
                fit_rows.append(_run_fit_task(**task))
        else:
            try:
                fit_executor = "process"
                with ProcessPoolExecutor(max_workers=fit_jobs) as executor:
                    futures = [executor.submit(_run_fit_task, **task) for task in fit_tasks]
                    for future in as_completed(futures):
                        fit_rows.append(future.result())
            except PermissionError:
                fit_rows.clear()
                fit_executor = "thread"
                with ThreadPoolExecutor(max_workers=fit_jobs) as executor:
                    futures = [executor.submit(_run_fit_task, **task) for task in fit_tasks]
                    for future in as_completed(futures):
                        fit_rows.append(future.result())

        fit_rows.sort(key=lambda row: (int(row["channel"]), int(row["intensity"])))
        with (fit_dir / "fit_summary.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(fit_rows[0].keys()))
            writer.writeheader()
            writer.writerows(fit_rows)

    report = {
        "run_dir": str(run_dir),
        "supplement_run_dirs": [str(p) for p in supplement_dirs],
        "reference_intensity": int(reference_intensity),
        "channels": channels,
        "waveform_len": waveform_len,
        "n_points": len(point_dirs),
        "output_dir": str(output_dir),
        "fit_channel": fit_channels,
        "fit_intensity": int(args.fit_intensity),
        "fit_all_points": bool(args.fit_all_points),
        "fit_jobs": int(fit_jobs),
        "fit_executor": fit_executor,
        "gaussian_max_peaks": int(args.gaussian_max_peaks),
        "vinogradov_nmax": int(args.vinogradov_nmax),
        "n_fit_tasks": len(fit_tasks),
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Reanalysis saved to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
