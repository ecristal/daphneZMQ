#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
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

from led_charge import load_channel_waves  # type: ignore


@dataclass(frozen=True)
class ChannelWindow:
    channel: int
    reference_intensity: int
    baseline_start: int
    baseline_stop: int
    onset_index: int
    peak_index: int
    integrate_start: int
    integrate_stop: int

    def as_dict(self) -> dict[str, int]:
        return {
            "channel": int(self.channel),
            "reference_intensity": int(self.reference_intensity),
            "baseline_start": int(self.baseline_start),
            "baseline_stop": int(self.baseline_stop),
            "onset_index": int(self.onset_index),
            "peak_index": int(self.peak_index),
            "integrate_start": int(self.integrate_start),
            "integrate_stop": int(self.integrate_stop),
        }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Analyze one channel across an LED scan with the pedestal fixed by the pre-pulse baseline."
    )
    ap.add_argument("run_dir", help="Primary run directory")
    ap.add_argument("--channel", type=int, required=True, help="Single channel to analyze")
    ap.add_argument(
        "--supplement-run-dir",
        action="append",
        default=[],
        help="Additional run dir whose analyzed points can fill missing intensities",
    )
    ap.add_argument("--output-dir", default="", help="Default: <run_dir>/single_channel_pe/ch<channel>")
    ap.add_argument("--waveform-len", type=int, default=0)
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed")
    ap.add_argument("--reference-intensity", type=int, default=0, help="Default: highest analyzed intensity")
    ap.add_argument("--search-start", type=int, default=80)
    ap.add_argument("--search-stop", type=int, default=220)
    ap.add_argument("--baseline-margin", type=int, default=12)
    ap.add_argument("--baseline-len", type=int, default=100)
    ap.add_argument("--pre-samples", type=int, default=4)
    ap.add_argument("--post-samples", type=int, default=12)
    ap.add_argument("--max-integration-len", type=int, default=40)
    ap.add_argument("--threshold-frac", type=float, default=0.10)
    ap.add_argument("--pre-pulse-reject-sigma", type=float, default=5.0)
    ap.add_argument("--target-zero-fraction", type=float, default=0.40)
    ap.add_argument("--plot-max-pe", type=int, default=6)
    ap.add_argument("--hist-bins", type=int, default=240)
    return ap.parse_args()


def load_manifest(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "scan_manifest.json").read_text(encoding="utf-8"))


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
            chosen[int(meta["intensity"])] = point_dir
    return dict(sorted(chosen.items()))


def robust_sigma(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 0.0
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    sigma = 1.4826 * mad
    if sigma <= 0.0:
        sigma = float(np.std(arr, ddof=0))
    return max(sigma, 1e-9)


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
    max_integration_len: int,
    threshold_frac: float,
) -> ChannelWindow:
    n_samples = int(mean_wf.size)
    s_lo = max(0, min(n_samples - 2, int(search_start)))
    s_hi = max(s_lo + 2, min(n_samples, int(search_stop)))

    rough_base = mean_wf[: max(32, s_lo)]
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
    threshold = max(float(threshold_frac) * peak_amplitude, 4.0 * baseline_rms)

    left = peak_rel
    while left > 0 and smooth[left] > threshold:
        left -= 1
    right = peak_rel
    while right < smooth.size - 1 and smooth[right] > threshold:
        right += 1

    onset_index = s_lo + left
    return_index = s_lo + right
    baseline_stop = max(24, onset_index - int(baseline_margin))
    baseline_start = max(0, baseline_stop - int(baseline_len))
    integrate_start = max(0, onset_index - int(pre_samples))
    integrate_stop = min(n_samples, return_index + int(post_samples))
    integrate_stop = min(integrate_stop, integrate_start + max(8, int(max_integration_len)))
    if integrate_stop <= integrate_start:
        integrate_stop = min(n_samples, integrate_start + max(8, int(post_samples)))

    return ChannelWindow(
        channel=int(channel),
        reference_intensity=int(reference_intensity),
        baseline_start=int(baseline_start),
        baseline_stop=int(baseline_stop),
        onset_index=int(onset_index),
        peak_index=int(peak_index),
        integrate_start=int(integrate_start),
        integrate_stop=int(integrate_stop),
    )


def baseline_subtract_waves(waves: np.ndarray, baseline_start: int, baseline_stop: int) -> np.ndarray:
    baseline = np.median(waves[:, baseline_start:baseline_stop], axis=1)
    return waves.astype(np.float64, copy=False) - baseline[:, np.newaxis]


def measure_charge_distributions(
    waves: np.ndarray,
    *,
    window: ChannelWindow,
    reject_sigma: float,
) -> dict[str, Any]:
    waves_bs = baseline_subtract_waves(waves, window.baseline_start, window.baseline_stop)
    baseline_region = waves_bs[:, window.baseline_start : window.baseline_stop]
    sample_sigma = robust_sigma(baseline_region.reshape(-1))
    if sample_sigma <= 0.0:
        sample_sigma = 1.0

    pre_max = np.max(np.abs(baseline_region), axis=1)
    clean_mask = pre_max < float(reject_sigma) * sample_sigma
    if not np.any(clean_mask):
        clean_mask = np.ones(waves_bs.shape[0], dtype=bool)

    waves_sel = waves_bs[clean_mask]
    signal_len = int(window.integrate_stop - window.integrate_start)
    ped_stop = int(window.baseline_stop)
    ped_start = max(int(window.baseline_start), ped_stop - signal_len)
    ped_stop = ped_start + signal_len

    signal_charges = waves_sel[:, window.integrate_start : window.integrate_stop].sum(axis=1)
    pedestal_charges = waves_sel[:, ped_start:ped_stop].sum(axis=1)

    pedestal_center = float(np.median(pedestal_charges))
    signal_charges = signal_charges - pedestal_center
    pedestal_charges = pedestal_charges - pedestal_center

    pedestal_sigma = robust_sigma(pedestal_charges)
    return {
        "signal_charges": signal_charges,
        "pedestal_charges": pedestal_charges,
        "sample_sigma": float(sample_sigma),
        "pedestal_sigma": float(pedestal_sigma),
        "pedestal_center_before_shift": float(pedestal_center),
        "n_waveforms": int(waves.shape[0]),
        "n_clean_waveforms": int(waves_sel.shape[0]),
        "pedestal_integrate_start": int(ped_start),
        "pedestal_integrate_stop": int(ped_stop),
    }


def gaussian_component(x: np.ndarray, amplitude: float, mean: float, sigma: float) -> np.ndarray:
    sigma = max(float(sigma), 1e-9)
    return amplitude * np.exp(-0.5 * ((x - mean) / sigma) ** 2)


def generalized_poisson_pmf(n: int, mu: float, lamb: float) -> float:
    if n == 0:
        return math.exp(-mu)
    inner = mu + lamb * n
    if inner <= 0:
        return 0.0
    return float(mu * (inner ** (n - 1)) * math.exp(-inner) / math.factorial(n))


def vinogradov_fixed_pedestal_model(
    x: np.ndarray,
    amplitude: float,
    gain: float,
    sigma1: float,
    mu: float,
    lamb: float,
    *,
    sigma0: float,
    nmax: int = 8,
) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for n in range(nmax + 1):
        weight = generalized_poisson_pmf(n, mu, lamb)
        sigma_n = math.sqrt(max(1e-9, sigma0 * sigma0 + n * sigma1 * sigma1))
        y += weight * np.exp(-0.5 * ((x - n * gain) / sigma_n) ** 2) / (sigma_n * math.sqrt(2.0 * math.pi))
    return amplitude * y


def fit_charge_histogram(charges: np.ndarray, pedestal_sigma: float, *, hist_bins: int) -> dict[str, Any]:
    charges = np.asarray(charges, dtype=float)
    charges = charges[np.isfinite(charges)]
    if charges.size < 100:
        return {"status": "insufficient_data", "pedestal_sigma": float(pedestal_sigma)}

    sigma0 = max(float(pedestal_sigma), 1e-6)
    hi = float(np.quantile(charges, 0.997))
    lo = float(min(np.quantile(charges, 0.001), -4.0 * sigma0))
    hi = max(hi, 6.0 * sigma0)
    counts, edges = np.histogram(charges, bins=hist_bins, range=(lo, hi))
    mids = 0.5 * (edges[:-1] + edges[1:])
    if np.max(counts) <= 0 or counts.size < 11:
        return {"status": "empty_histogram", "pedestal_sigma": float(sigma0)}

    positive_mask = mids > 0.5 * sigma0
    mids_pos = mids[positive_mask]
    counts_pos = counts[positive_mask]
    if counts_pos.size < 11:
        return {
            "status": "insufficient_positive_histogram",
            "pedestal_sigma": float(sigma0),
            "histogram": {"bin_centers": mids.tolist(), "counts": counts.tolist()},
        }

    smooth = savgol_filter(counts_pos, 11, 3)
    peaks, _ = find_peaks(smooth, prominence=max(3.0, float(np.max(smooth)) * 0.01), distance=6)
    peak_positions = mids_pos[peaks]
    if peak_positions.size < 2:
        return {
            "status": "no_peak_ladder",
            "pedestal_sigma": float(sigma0),
            "histogram": {"bin_centers": mids.tolist(), "counts": counts.tolist()},
            "peak_positions": peak_positions.tolist(),
        }

    peak_positions = peak_positions[:6]
    counts_guess = counts_pos[peaks[: len(peak_positions)]]
    gain0 = float(np.median(np.diff(peak_positions)))
    sigma1_0 = max(float(np.diff(edges)[0]) * 2.0, gain0 / 5.0)
    amp0 = float(np.sum(counts) * np.diff(edges)[0])
    p0 = [amp0, max(gain0, 1.0), max(sigma1_0, sigma0 * 0.5), 1.0, 0.1]
    lo_b = [0.0, max(1.0, gain0 * 0.4), 1.0, 0.01, 0.0]
    hi_b = [amp0 * 10.0, gain0 * 1.8 if gain0 > 0 else hi, gain0, 8.0, 0.95]

    result: dict[str, Any] = {
        "status": "ok",
        "pedestal_sigma": float(sigma0),
        "histogram": {"bin_centers": mids.tolist(), "counts": counts.tolist()},
        "peak_positions": peak_positions.tolist(),
    }

    try:
        popt, _ = curve_fit(
            lambda x, amplitude, gain, sigma1, mu, lamb: vinogradov_fixed_pedestal_model(
                x, amplitude, gain, sigma1, mu, lamb, sigma0=sigma0
            ),
            mids,
            counts,
            p0=p0,
            bounds=(lo_b, hi_b),
            maxfev=50000,
        )
        amplitude, gain, sigma1, mu, lamb = [float(v) for v in popt]
        result["vinogradov_like_fit"] = {
            "status": "ok",
            "params": {
                "amplitude": amplitude,
                "pedestal": 0.0,
                "gain": gain,
                "sigma0": float(sigma0),
                "sigma1": sigma1,
                "mu": mu,
                "lambda": lamb,
            },
        }
    except Exception as exc:
        result["vinogradov_like_fit"] = {"status": "failed", "error": str(exc)}

    return result


def save_histogram_plot(
    path: Path,
    *,
    charges: np.ndarray,
    fit_result: dict[str, Any],
    title: str,
    max_pe: int,
) -> None:
    if plt is None:
        return

    charges = np.asarray(charges, dtype=float)
    charges = charges[np.isfinite(charges)]

    sigma0 = float(fit_result.get("pedestal_sigma", robust_sigma(charges)))
    v_fit = fit_result.get("vinogradov_like_fit", {})
    if v_fit.get("status") == "ok":
        params = v_fit["params"]
        gain = float(params["gain"])
        xmax = max(float((max_pe + 0.75) * gain), float(np.quantile(charges, 0.90)))
    else:
        gain = math.nan
        xmax = float(np.quantile(charges, 0.98))
    xmin = min(-4.0 * sigma0, float(np.quantile(charges, 0.01)))

    counts, edges = np.histogram(charges, bins=240, range=(xmin, xmax))
    mids = 0.5 * (edges[:-1] + edges[1:])

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.step(mids, counts, where="mid", color="#4C72B0", linewidth=1.2, label="Signal window")

    if v_fit.get("status") == "ok":
        params = v_fit["params"]
        y = vinogradov_fixed_pedestal_model(
            mids,
            params["amplitude"],
            params["gain"],
            params["sigma1"],
            params["mu"],
            params["lambda"],
            sigma0=params["sigma0"],
        )
        ax.plot(mids, y, color="#55A868", lw=1.5, label="Total fit")
        for n in range(1, max_pe + 1):
            weight = generalized_poisson_pmf(n, params["mu"], params["lambda"])
            sigma_n = math.sqrt(max(1e-9, params["sigma0"] ** 2 + n * params["sigma1"] ** 2))
            amp_n = params["amplitude"] * weight / (sigma_n * math.sqrt(2.0 * math.pi))
            label = "PE components" if n == 1 else None
            ax.plot(
                mids,
                gaussian_component(mids, amp_n, n * params["gain"], sigma_n),
                color="#C44E52",
                lw=1.0,
                linestyle="--",
                alpha=0.85,
                label=label,
            )
        snr = params["gain"] / max(params["sigma0"], 1e-9)
        ax.text(
            0.97,
            0.96,
            f"S/N = {snr:.2f}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            bbox={"facecolor": "white", "edgecolor": "0.8", "alpha": 0.9},
        )

    ax.set_xlim(xmin, xmax)
    ax.set_xlabel("Integrated charge")
    ax.set_ylabel("Counts")
    ax.set_title(title)
    ax.grid(True, alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def save_selection_plot(path: Path, rows: list[dict[str, Any]], *, target_zero_fraction: float, channel: int) -> None:
    if plt is None or not rows:
        return
    xs = np.array([int(row["intensity"]) for row in rows], dtype=float)
    ys = np.array([float(row["zero_fraction_data"]) for row in rows], dtype=float)
    mask = np.isfinite(ys)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs[mask], ys[mask], marker="o", color="#4C72B0")
    ax.axhline(float(target_zero_fraction), color="#C44E52", linestyle="--", linewidth=1.0, label="Target P0")
    best_rows = [row for row in rows if row.get("selected")]
    if best_rows:
        best = best_rows[0]
        ax.scatter([best["intensity"]], [best["zero_fraction_data"]], color="#55A868", s=65, zorder=5, label="Selected")
    ax.set_xlabel("LED intensity")
    ax.set_ylabel("Zero-PE fraction")
    ax.set_title(f"ch{channel} zero-PE occupancy vs intensity")
    ax.grid(True, alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    supplement_dirs = [Path(p).expanduser().resolve() for p in args.supplement_run_dir]
    manifest = load_manifest(run_dir)
    waveform_len = int(args.waveform_len or manifest.get("waveform_len", 1024))
    channel = int(args.channel)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else (run_dir / "single_channel_pe" / f"ch{channel:02d}")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    point_dirs = gather_analyzed_points([run_dir, *supplement_dirs])
    if not point_dirs:
        raise RuntimeError(f"No analyzed points found under {run_dir}")

    reference_intensity = int(args.reference_intensity) if args.reference_intensity > 0 else max(point_dirs)
    reference_dir = point_dirs[reference_intensity]
    reference_waves = load_channel_waves(
        reference_dir / "raw" / f"channel_{channel}.dat",
        waveform_len,
        interpret=args.interpret,
    )
    mean_wf = reference_waves.astype(np.float64, copy=False).mean(axis=0)
    window = derive_window_from_mean(
        mean_wf,
        channel=channel,
        reference_intensity=reference_intensity,
        search_start=args.search_start,
        search_stop=args.search_stop,
        baseline_margin=args.baseline_margin,
        baseline_len=args.baseline_len,
        pre_samples=args.pre_samples,
        post_samples=args.post_samples,
        max_integration_len=args.max_integration_len,
        threshold_frac=args.threshold_frac,
    )

    rows: list[dict[str, Any]] = []
    best_row: dict[str, Any] | None = None
    for intensity, point_dir in point_dirs.items():
        waves = load_channel_waves(point_dir / "raw" / f"channel_{channel}.dat", waveform_len, interpret=args.interpret)
        charge_info = measure_charge_distributions(
            waves,
            window=window,
            reject_sigma=float(args.pre_pulse_reject_sigma),
        )
        fit_result = fit_charge_histogram(
            charge_info["signal_charges"],
            charge_info["pedestal_sigma"],
            hist_bins=args.hist_bins,
        )

        zero_fraction_data = math.nan
        zero_fraction_fit = math.nan
        separation = math.nan
        gain = math.nan
        snr = math.nan
        snr_combined = math.nan
        fit_ok = fit_result.get("vinogradov_like_fit", {}).get("status") == "ok"
        if fit_ok:
            params = fit_result["vinogradov_like_fit"]["params"]
            gain = float(params["gain"])
            zero_fraction_data = float(np.mean(np.asarray(charge_info["signal_charges"]) < 0.5 * gain))
            zero_fraction_fit = math.exp(-float(params["mu"]))
            separation = float(gain / max(float(params["sigma0"]), 1e-9))
            snr = float(gain / max(float(params["sigma0"]), 1e-9))
            snr_combined = float(
                gain
                / math.sqrt(max(1e-9, float(params["sigma0"]) ** 2 + float(params["sigma1"]) ** 2))
            )

        score = float("inf")
        if fit_ok and np.isfinite(zero_fraction_data):
            score = abs(zero_fraction_data - float(args.target_zero_fraction)) + max(0.0, 1.5 - separation)

        fit_payload = {
            "window": window.as_dict(),
            "charge_info": {
                "n_waveforms": charge_info["n_waveforms"],
                "n_clean_waveforms": charge_info["n_clean_waveforms"],
                "sample_sigma": charge_info["sample_sigma"],
                "pedestal_sigma": charge_info["pedestal_sigma"],
                "pedestal_center_before_shift": charge_info["pedestal_center_before_shift"],
                "pedestal_integrate_start": charge_info["pedestal_integrate_start"],
                "pedestal_integrate_stop": charge_info["pedestal_integrate_stop"],
            },
            "fit_result": fit_result,
        }
        (output_dir / f"fit_intensity_{intensity:04d}.json").write_text(
            json.dumps(fit_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        row = {
            "channel": channel,
            "intensity": int(intensity),
            "point_dir": str(point_dir),
            "vinogradov_status": fit_result.get("vinogradov_like_fit", {}).get("status", "missing"),
            "zero_fraction_data": zero_fraction_data,
            "zero_fraction_fit": zero_fraction_fit,
            "separation": separation,
            "gain": gain,
            "snr": snr,
            "snr_combined": snr_combined,
            "pedestal_sigma": charge_info["pedestal_sigma"],
            "pedestal_center_before_shift": charge_info["pedestal_center_before_shift"],
            "n_waveforms": charge_info["n_waveforms"],
            "n_clean_waveforms": charge_info["n_clean_waveforms"],
            "score": score,
            "selected": False,
        }
        rows.append(row)
        if fit_ok and (best_row is None or score < float(best_row["score"])):
            best_row = row

    if best_row is not None:
        best_row["selected"] = True

    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    if best_row is not None:
        best_intensity = int(best_row["intensity"])
        waves = load_channel_waves(
            point_dirs[best_intensity] / "raw" / f"channel_{channel}.dat",
            waveform_len,
            interpret=args.interpret,
        )
        charge_info = measure_charge_distributions(
            waves,
            window=window,
            reject_sigma=float(args.pre_pulse_reject_sigma),
        )
        fit_payload = json.loads((output_dir / f"fit_intensity_{best_intensity:04d}.json").read_text(encoding="utf-8"))
        save_histogram_plot(
            output_dir / f"selected_histogram_intensity_{best_intensity:04d}.png",
            charges=np.asarray(charge_info["signal_charges"], dtype=float),
            fit_result=fit_payload["fit_result"],
            title=f"{run_dir.name} ch{channel} intensity={best_intensity} first PE peaks",
            max_pe=int(args.plot_max_pe),
        )

    save_selection_plot(
        output_dir / "zero_fraction_vs_intensity.png",
        rows,
        target_zero_fraction=float(args.target_zero_fraction),
        channel=channel,
    )
    (output_dir / "channel_window.json").write_text(json.dumps(window.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = {
        "run_dir": str(run_dir),
        "supplement_run_dirs": [str(p) for p in supplement_dirs],
        "channel": channel,
        "reference_intensity": int(reference_intensity),
        "waveform_len": waveform_len,
        "target_zero_fraction": float(args.target_zero_fraction),
        "selected_intensity": None if best_row is None else int(best_row["intensity"]),
        "window": window.as_dict(),
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Single-channel PE analysis saved to {output_dir}")
    if best_row is not None:
        print(
            f"Selected intensity {int(best_row['intensity'])} for ch{channel}: "
            f"zero_fraction={float(best_row['zero_fraction_data']):.3f} "
            f"gain={float(best_row['gain']):.3f} "
            f"sigma0={float(best_row['pedestal_sigma']):.3f} "
            f"snr={float(best_row['snr']):.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
