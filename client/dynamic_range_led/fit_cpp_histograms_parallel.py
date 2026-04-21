#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import curve_fit

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
except Exception:
    plt = None


HIST_RE = re.compile(r"^ch(?P<channel>\d+)_intensity_(?P<intensity>\d+)_histogram\.csv$")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Fit cpp_snr_scan histogram CSVs in parallel.")
    ap.add_argument("run_dir", help="Run directory that contains cpp_snr_scan_p30")
    ap.add_argument("--cpp-dir", default="cpp_snr_scan_p30", help="Subdirectory under run_dir")
    ap.add_argument(
        "--output-dir",
        default="",
        help="Default: <run_dir>/<cpp-dir>/vinogradov_reanalysis_parallel",
    )
    ap.add_argument(
        "--jobs",
        type=int,
        default=0,
        help="Worker count. Default uses a bounded CPU-based value.",
    )
    ap.add_argument(
        "--max-peaks",
        type=int,
        default=8,
        help="Maximum number of non-pedestal Gaussian components to fit.",
    )
    ap.add_argument(
        "--vinogradov-nmax",
        type=int,
        default=10,
        help="Maximum PE multiplicity term in the Vinogradov-like sum.",
    )
    ap.add_argument(
        "--min-component-area-fraction",
        type=float,
        default=0.01,
        help="Ignore cpp peak components whose area is below this fraction of the total histogram counts.",
    )
    ap.add_argument(
        "--channels",
        default="",
        help="Optional comma-separated channel filter.",
    )
    ap.add_argument(
        "--intensities",
        default="",
        help="Optional comma-separated intensity filter.",
    )
    ap.add_argument("--xmin", type=float, default=-2500.0, help="Fixed x-axis minimum for saved plots.")
    ap.add_argument("--xmax", type=float, default=20000.0, help="Fixed x-axis maximum for saved plots.")
    return ap.parse_args()


def parse_int_list(value: str) -> set[int]:
    out: set[int] = set()
    for token in value.split(","):
        token = token.strip()
        if token:
            out.add(int(token))
    return out


def _resolve_jobs(requested_jobs: int, n_tasks: int) -> int:
    if n_tasks <= 1:
        return 1
    if requested_jobs > 0:
        return max(1, min(int(requested_jobs), n_tasks))
    cpu_count = os.cpu_count() or 1
    return max(1, min(n_tasks, cpu_count - 1 if cpu_count > 1 else 1))


def preferred_monospace_font() -> str:
    if plt is None:
        return "monospace"
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono", ".SF NS Mono"):
        if candidate in installed:
            return candidate
    return "monospace"


def configure_style() -> None:
    if plt is None:
        return
    plt.rcParams.update(
        {
            "figure.figsize": (7.2, 4.8),
            "figure.dpi": 180,
            "savefig.dpi": 220,
            "font.family": preferred_monospace_font(),
            "font.size": 12,
            "axes.labelsize": 13,
            "axes.titlesize": 11,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 9,
            "legend.frameon": False,
            "grid.alpha": 0.0,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
        }
    )


def read_summary(summary_csv: Path) -> dict[tuple[int, int], dict[str, Any]]:
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    with summary_csv.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                key = (int(row["channel"]), int(row["intensity"]))
            except Exception:
                continue
            rows[key] = row
    return rows


def _to_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def load_histogram(hist_path: Path) -> dict[str, Any]:
    with hist_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if not rows:
        raise RuntimeError(f"Empty histogram: {hist_path}")

    x = np.asarray([float(row["x"]) for row in rows], dtype=float)
    count = np.asarray([float(row["count"]) for row in rows], dtype=float)
    total_fit = np.asarray([float(row.get("total_fit", 0.0)) for row in rows], dtype=float)
    components: dict[str, np.ndarray] = {}
    for name in fieldnames:
        if name.startswith("peak_"):
            components[name] = np.asarray([float(row.get(name, 0.0)) for row in rows], dtype=float)
    return {
        "x": x,
        "count": count,
        "total_fit": total_fit,
        "components": components,
    }


def area_gaussian(x: np.ndarray, n_events: float, mean: float, sigma: float, bin_width: float) -> np.ndarray:
    sigma = max(float(sigma), 1e-9)
    norm = float(n_events) * float(bin_width) / (math.sqrt(2.0 * math.pi) * sigma)
    return norm * np.exp(-0.5 * ((x - mean) / sigma) ** 2)


def gaussian_ladder_counts_model(x: np.ndarray, *params: float, bin_width: float) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for idx in range(0, len(params), 3):
        n_events, mean, sigma = params[idx : idx + 3]
        y += area_gaussian(x, n_events, mean, sigma, bin_width)
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
    nmax: int,
) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for n in range(max(1, int(nmax)) + 1):
        weight = generalized_poisson_pmf(n, mu, lamb)
        sigma_n = math.sqrt(max(1e-9, sigma0 * sigma0 + n * sigma1 * sigma1))
        y += weight * np.exp(-0.5 * ((x - (pedestal + n * gain)) / sigma_n) ** 2) / (
            sigma_n * math.sqrt(2.0 * math.pi)
        )
    return amplitude * y


def weighted_mean_sigma(x: np.ndarray, y: np.ndarray, fallback_sigma: float) -> tuple[float, float, float]:
    weights = np.clip(np.asarray(y, dtype=float), 0.0, None)
    total = float(np.sum(weights))
    if total <= 0.0:
        idx = int(np.argmax(y)) if y.size else 0
        center = float(x[idx]) if x.size else 0.0
        return center, max(float(fallback_sigma), 1.0), 0.0
    center = float(np.sum(x * weights) / total)
    variance = float(np.sum(weights * (x - center) ** 2) / total)
    sigma = math.sqrt(max(variance, float(fallback_sigma) * float(fallback_sigma), 1.0))
    return center, sigma, total


def component_seeds(
    x: np.ndarray,
    components: dict[str, np.ndarray],
    *,
    total_counts: float,
    min_area_fraction: float,
    max_peaks: int,
    fallback_sigma: float,
) -> list[dict[str, float]]:
    seeds: list[dict[str, float]] = []
    area_cut = max(5.0, float(min_area_fraction) * float(total_counts))
    for name, comp in sorted(components.items()):
        area = float(np.sum(np.clip(comp, 0.0, None)))
        if area < area_cut or float(np.max(comp)) <= 0.0:
            continue
        mean, sigma, _ = weighted_mean_sigma(x, comp, fallback_sigma=fallback_sigma)
        seeds.append(
            {
                "name": name,
                "n_events": area,
                "mean": mean,
                "sigma": sigma,
                "height": float(np.max(comp)),
            }
        )
    seeds.sort(key=lambda item: item["mean"])
    return seeds[: max(0, int(max_peaks))]


def estimate_pedestal_seed(
    x: np.ndarray,
    count: np.ndarray,
    *,
    sigma0: float,
    n_clean_waveforms: float,
    zero_fraction: float,
    bin_width: float,
) -> dict[str, float]:
    sigma0 = max(float(sigma0), float(bin_width), 1.0)
    mask = np.abs(x) <= 4.0 * sigma0
    if np.any(mask) and float(np.sum(np.clip(count[mask], 0.0, None))) > 0.0:
        mean, sigma_est, area = weighted_mean_sigma(x[mask], count[mask], fallback_sigma=sigma0)
        sigma0 = max(sigma0, sigma_est)
        n0_from_shape = area
    else:
        mean = 0.0
        n0_from_shape = 0.0

    if np.isfinite(zero_fraction) and np.isfinite(n_clean_waveforms) and 0.0 < zero_fraction < 1.0 and n_clean_waveforms > 0.0:
        n0 = zero_fraction * n_clean_waveforms
    else:
        peak0 = float(np.max(count[mask])) if np.any(mask) else float(np.max(count))
        n0 = peak0 * math.sqrt(2.0 * math.pi) * sigma0 / max(bin_width, 1e-9)
    if not np.isfinite(n0) or n0 <= 0.0:
        n0 = max(n0_from_shape, 1.0)
    return {"n_events": float(n0), "mean": float(mean), "sigma": float(sigma0)}


def reduced_chi2(observed: np.ndarray, expected: np.ndarray, n_params: int) -> float:
    obs = np.asarray(observed, dtype=float)
    exp = np.asarray(expected, dtype=float)
    sigma = np.sqrt(np.clip(obs, 1.0, None))
    dof = max(1, int(obs.size) - int(n_params))
    return float(np.sum(((obs - exp) / sigma) ** 2) / dof)


def fit_histogram(
    x: np.ndarray,
    count: np.ndarray,
    components: dict[str, np.ndarray],
    summary_row: dict[str, Any],
    *,
    max_peaks: int,
    vinogradov_nmax: int,
    min_area_fraction: float,
) -> dict[str, Any]:
    x = np.asarray(x, dtype=float)
    count = np.asarray(count, dtype=float)
    if x.size < 8 or count.size != x.size or float(np.sum(count)) <= 0.0:
        return {"status": "empty_histogram"}

    bin_width = float(np.median(np.diff(x))) if x.size > 1 else 1.0
    total_counts = float(np.sum(np.clip(count, 0.0, None)))
    sigma0_seed = max(_to_float(summary_row.get("pedestal_sigma"), 1.0), bin_width, 1.0)
    first_peak_mean = _to_float(summary_row.get("first_peak_mean"), math.nan)
    first_peak_sigma = _to_float(summary_row.get("first_peak_sigma"), math.nan)
    zero_fraction = _to_float(summary_row.get("zero_fraction"), math.nan)
    n_clean_waveforms = _to_float(summary_row.get("n_clean_waveforms"), total_counts)

    pe_seeds = component_seeds(
        x,
        components,
        total_counts=total_counts,
        min_area_fraction=min_area_fraction,
        max_peaks=max_peaks,
        fallback_sigma=max(sigma0_seed * 1.3, 2.0 * bin_width),
    )
    if len(pe_seeds) < 1 and np.isfinite(first_peak_mean) and first_peak_mean > 3.0 * sigma0_seed:
        sigma_guess = max(first_peak_sigma, sigma0_seed * 1.4, 2.0 * bin_width) if np.isfinite(first_peak_sigma) else max(
            sigma0_seed * 1.4, 2.0 * bin_width
        )
        pe_seeds = [{"name": "peak_1", "n_events": max(total_counts * 0.1, 1.0), "mean": float(first_peak_mean), "sigma": sigma_guess, "height": float(np.max(count))}]
    if len(pe_seeds) < 1:
        return {"status": "no_peak_components"}

    ped_seed = estimate_pedestal_seed(
        x,
        count,
        sigma0=sigma0_seed,
        n_clean_waveforms=n_clean_waveforms,
        zero_fraction=zero_fraction,
        bin_width=bin_width,
    )

    gain_candidates: list[float] = []
    if len(pe_seeds) >= 2:
        gain_candidates.extend(float(v) for v in np.diff([seed["mean"] for seed in pe_seeds]) if float(v) > 0.0)
    if np.isfinite(first_peak_mean) and first_peak_mean > ped_seed["mean"]:
        gain_candidates.append(float(first_peak_mean - ped_seed["mean"]))
    gain0 = float(np.median(gain_candidates)) if gain_candidates else float(max(pe_seeds[0]["mean"] - ped_seed["mean"], 1.0))
    gain0 = max(gain0, 3.0 * bin_width, sigma0_seed * 2.5)

    sigma1_seed = max(
        math.sqrt(max(first_peak_sigma * first_peak_sigma - sigma0_seed * sigma0_seed, bin_width * bin_width))
        if np.isfinite(first_peak_sigma) and first_peak_sigma > sigma0_seed
        else max(pe_seeds[0]["sigma"], sigma0_seed),
        bin_width,
    )

    gaussian_seeds = [ped_seed] + pe_seeds
    g_init: list[float] = []
    g_lo: list[float] = []
    g_hi: list[float] = []
    for idx, seed in enumerate(gaussian_seeds):
        n_events = max(float(seed["n_events"]), 1.0)
        mean = float(seed["mean"])
        sigma = max(float(seed["sigma"]), bin_width, 1.0)
        mu_pad = 1.5 * sigma if idx == 0 else max(0.35 * gain0, 1.25 * sigma)
        sigma_hi = max(2.0 * sigma, 0.65 * gain0)
        g_init.extend([n_events, mean, sigma])
        g_lo.extend([0.0, mean - mu_pad, max(0.4 * sigma, 0.5 * bin_width)])
        g_hi.extend([total_counts * 2.0, mean + mu_pad, sigma_hi])

    result: dict[str, Any] = {
        "status": "ok",
        "bin_width": float(bin_width),
        "total_counts": float(total_counts),
        "pedestal_seed": ped_seed,
        "pe_seeds": pe_seeds,
    }

    sigma_y = np.sqrt(np.clip(count, 4.0, None))

    try:
        g_popt, _ = curve_fit(
            lambda xx, *params: gaussian_ladder_counts_model(xx, *params, bin_width=bin_width),
            x,
            count,
            p0=g_init,
            bounds=(g_lo, g_hi),
            sigma=sigma_y,
            absolute_sigma=False,
            maxfev=100000,
        )
        g_curve = gaussian_ladder_counts_model(x, *g_popt, bin_width=bin_width)
        comps: list[dict[str, float]] = []
        for idx in range(0, len(g_popt), 3):
            n_events, mean, sigma = g_popt[idx : idx + 3]
            comps.append(
                {
                    "index": idx // 3,
                    "n_events": float(n_events),
                    "mean": float(mean),
                    "sigma": float(sigma),
                }
            )
        result["gaussian_ladder_fit"] = {
            "status": "ok",
            "n_components": len(comps),
            "params": comps,
            "reduced_chi2": reduced_chi2(count, g_curve, len(g_popt)),
        }
    except Exception as exc:
        result["gaussian_ladder_fit"] = {"status": "failed", "error": str(exc)}

    try:
        amp0 = total_counts * bin_width
        mu_occ = -math.log(max(1e-6, min(0.999999, zero_fraction))) if np.isfinite(zero_fraction) and 0.0 < zero_fraction < 1.0 else 1.5
        v_p0 = [amp0, ped_seed["mean"], gain0, sigma0_seed, sigma1_seed, mu_occ, 0.05]
        v_lo = [
            0.2 * amp0,
            ped_seed["mean"] - 2.0 * sigma0_seed,
            0.6 * gain0,
            max(0.5 * bin_width, 0.5 * sigma0_seed),
            max(0.5 * bin_width, 0.2 * sigma1_seed),
            0.01,
            0.0,
        ]
        v_hi = [
            5.0 * amp0,
            ped_seed["mean"] + 2.0 * sigma0_seed,
            1.5 * gain0,
            min(0.6 * gain0, 1.8 * sigma0_seed),
            min(gain0, 2.0 * sigma1_seed),
            8.0,
            0.95,
        ]
        v_model = lambda xx, amplitude, pedestal, gain, sigma0, sigma1, mu, lamb: vinogradov_like_model(  # noqa: E731
            xx,
            amplitude,
            pedestal,
            gain,
            sigma0,
            sigma1,
            mu,
            lamb,
            nmax=max(1, int(vinogradov_nmax)),
        )
        v_popt, _ = curve_fit(
            v_model,
            x,
            count,
            p0=v_p0,
            bounds=(v_lo, v_hi),
            sigma=sigma_y,
            absolute_sigma=False,
            maxfev=100000,
        )
        v_curve = v_model(x, *v_popt)
        params = {
            "amplitude": float(v_popt[0]),
            "pedestal": float(v_popt[1]),
            "gain": float(v_popt[2]),
            "sigma0": float(v_popt[3]),
            "sigma1": float(v_popt[4]),
            "mu": float(v_popt[5]),
            "lambda": float(v_popt[6]),
        }
        result["vinogradov_like_fit"] = {
            "status": "ok",
            "nmax": int(vinogradov_nmax),
            "params": params,
            "reduced_chi2": reduced_chi2(count, v_curve, len(v_popt)),
        }
    except Exception as exc:
        result["vinogradov_like_fit"] = {"status": "failed", "error": str(exc)}

    result["histogram"] = {
        "bin_centers": [float(v) for v in x],
        "counts": [float(v) for v in count],
    }
    return result


def save_fit_plot(
    path: Path,
    *,
    x: np.ndarray,
    count: np.ndarray,
    fit_result: dict[str, Any],
    title: str,
    xmin: float,
    xmax: float,
) -> None:
    if plt is None:
        return
    x = np.asarray(x, dtype=float)
    count = np.asarray(count, dtype=float)
    bin_width = float(fit_result.get("bin_width", np.median(np.diff(x)) if x.size > 1 else 1.0))

    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.step(x, count, where="mid", color="#4C72B0", lw=1.2, label="Histogram")

    g_fit = fit_result.get("gaussian_ladder_fit", {})
    if g_fit.get("status") == "ok":
        params = g_fit.get("params", [])
        flat: list[float] = []
        for comp in params:
            flat.extend([comp["n_events"], comp["mean"], comp["sigma"]])
        y = gaussian_ladder_counts_model(x, *flat, bin_width=bin_width)
        ax.plot(x, y, color="#C44E52", lw=1.5, label="Gaussian ladder")
        for idx, comp in enumerate(params):
            label = "Gaussian components" if idx == 0 else None
            ax.plot(
                x,
                area_gaussian(x, comp["n_events"], comp["mean"], comp["sigma"], bin_width),
                color="#C44E52",
                linestyle="--",
                alpha=0.65,
                lw=0.9,
                label=label,
            )

    v_fit = fit_result.get("vinogradov_like_fit", {})
    if v_fit.get("status") == "ok":
        p = v_fit["params"]
        y = vinogradov_like_model(
            x,
            p["amplitude"],
            p["pedestal"],
            p["gain"],
            p["sigma0"],
            p["sigma1"],
            p["mu"],
            p["lambda"],
            nmax=int(v_fit.get("nmax", 8)),
        )
        ax.plot(x, y, color="#55A868", lw=1.6, label="Vinogradov-like")
        for n in range(0, int(v_fit.get("nmax", 8)) + 1):
            weight = generalized_poisson_pmf(n, p["mu"], p["lambda"])
            sigma_n = math.sqrt(max(1e-9, p["sigma0"] ** 2 + n * p["sigma1"] ** 2))
            y_n = p["amplitude"] * weight * np.exp(-0.5 * ((x - (p["pedestal"] + n * p["gain"])) / sigma_n) ** 2) / (
                sigma_n * math.sqrt(2.0 * math.pi)
            )
            label = "Vinogradov components" if n == 0 else None
            ax.plot(x, y_n, color="#55A868", linestyle=":", lw=0.9, alpha=0.75, label=label)

    text_lines: list[str] = []
    if g_fit.get("status") == "ok":
        text_lines.append(f"Gauss chi2r={float(g_fit['reduced_chi2']):.2f}")
    if v_fit.get("status") == "ok":
        p = v_fit["params"]
        gain = float(p["gain"])
        sigma0 = max(float(p["sigma0"]), 1e-9)
        sigma1 = max(float(p["sigma1"]), 1e-9)
        snr_combined = gain / math.sqrt(sigma0 * sigma0 + sigma1 * sigma1)
        snr_ped = gain / sigma0
        text_lines.append(f"Vin chi2r={float(v_fit['reduced_chi2']):.2f}")
        text_lines.append(f"gain={gain:.1f}")
        text_lines.append(f"s0={sigma0:.1f}")
        text_lines.append(f"s1={sigma1:.1f}")
        text_lines.append(f"mu={float(p['mu']):.2f}")
        text_lines.append(f"lambda={float(p['lambda']):.2f}")
        text_lines.append(f"S/N={snr_combined:.2f}")
        text_lines.append(f"alt={snr_ped:.2f}")
    if text_lines:
        ax.text(
            0.985,
            0.98,
            "\n".join(text_lines),
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=9,
        )

    ax.set_xlim(float(xmin), float(xmax))
    ax.set_xlabel("Integrated charge")
    ax.set_ylabel("Counts")
    ax.set_title(title, fontsize=11)
    ax.grid(False)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.06), frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)


def _fit_task(
    *,
    hist_path: str,
    summary_row: dict[str, Any],
    output_base: str,
    run_name: str,
    max_peaks: int,
    vinogradov_nmax: int,
    min_area_fraction: float,
    xmin: float,
    xmax: float,
) -> dict[str, Any]:
    src = Path(hist_path)
    out_base = Path(output_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    match = HIST_RE.match(src.name)
    if not match:
        raise RuntimeError(f"Unexpected histogram filename: {src.name}")
    channel = int(match.group("channel"))
    intensity = int(match.group("intensity"))

    hist = load_histogram(src)
    fit_result = fit_histogram(
        hist["x"],
        hist["count"],
        hist["components"],
        summary_row,
        max_peaks=max_peaks,
        vinogradov_nmax=vinogradov_nmax,
        min_area_fraction=min_area_fraction,
    )
    json_path = out_base.with_suffix(".json")
    png_path = out_base.with_suffix(".png")
    json_path.write_text(json.dumps(fit_result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    save_fit_plot(
        png_path,
        x=hist["x"],
        count=hist["count"],
        fit_result=fit_result,
        title=f"{run_name} ch{channel:02d} intensity={intensity}",
        xmin=xmin,
        xmax=xmax,
    )

    g_fit = fit_result.get("gaussian_ladder_fit", {})
    v_fit = fit_result.get("vinogradov_like_fit", {})
    v_params = v_fit.get("params", {}) if isinstance(v_fit, dict) else {}
    gain = _to_float(v_params.get("gain"))
    sigma0 = _to_float(v_params.get("sigma0"))
    sigma1 = _to_float(v_params.get("sigma1"))
    vinogradov_snr_ped = math.nan
    vinogradov_snr_combined = math.nan
    if np.isfinite(gain) and np.isfinite(sigma0) and sigma0 > 0.0:
        vinogradov_snr_ped = gain / sigma0
    if np.isfinite(gain) and np.isfinite(sigma0) and np.isfinite(sigma1):
        denom = math.sqrt(max(1e-9, sigma0 * sigma0 + sigma1 * sigma1))
        vinogradov_snr_combined = gain / denom
    return {
        "channel": int(channel),
        "intensity": int(intensity),
        "histogram_csv": str(src),
        "json_path": str(json_path),
        "png_path": str(png_path),
        "status": str(fit_result.get("status", "ok")),
        "n_seed_peaks": int(len(fit_result.get("pe_seeds", []))),
        "gaussian_status": str(g_fit.get("status", "missing")),
        "gaussian_n_components": int(g_fit.get("n_components", 0)) if g_fit.get("n_components") is not None else 0,
        "gaussian_reduced_chi2": _to_float(g_fit.get("reduced_chi2")),
        "vinogradov_status": str(v_fit.get("status", "missing")),
        "vinogradov_reduced_chi2": _to_float(v_fit.get("reduced_chi2")),
        "gain": gain,
        "sigma0": sigma0,
        "sigma1": sigma1,
        "vinogradov_snr_ped": vinogradov_snr_ped,
        "vinogradov_snr_combined": vinogradov_snr_combined,
        "mu": _to_float(v_params.get("mu")),
        "lambda": _to_float(v_params.get("lambda")),
    }


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    cpp_dir = (run_dir / args.cpp_dir).resolve()
    hist_dir = cpp_dir / "all_histograms"
    summary_csv = cpp_dir / "summary_by_point_channel.csv"
    if not hist_dir.is_dir():
        raise RuntimeError(f"Missing histogram directory: {hist_dir}")
    if not summary_csv.exists():
        raise RuntimeError(f"Missing summary CSV: {summary_csv}")

    channel_filter = parse_int_list(args.channels)
    intensity_filter = parse_int_list(args.intensities)
    summary_rows = read_summary(summary_csv)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else (cpp_dir / "vinogradov_reanalysis_parallel")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    fit_dir = output_dir / "fits"
    fit_dir.mkdir(exist_ok=True)

    tasks: list[dict[str, Any]] = []
    for hist_path in sorted(hist_dir.glob("*.csv")):
        match = HIST_RE.match(hist_path.name)
        if not match:
            continue
        channel = int(match.group("channel"))
        intensity = int(match.group("intensity"))
        if channel_filter and channel not in channel_filter:
            continue
        if intensity_filter and intensity not in intensity_filter:
            continue
        key = (channel, intensity)
        if key not in summary_rows:
            continue
        tasks.append(
            {
                "hist_path": str(hist_path),
                "summary_row": summary_rows[key],
                "output_base": str(fit_dir / hist_path.stem),
                "run_name": run_dir.name,
                "max_peaks": int(args.max_peaks),
                "vinogradov_nmax": int(args.vinogradov_nmax),
                "min_area_fraction": float(args.min_component_area_fraction),
                "xmin": float(args.xmin),
                "xmax": float(args.xmax),
            }
        )

    if not tasks:
        raise RuntimeError("No histogram tasks selected")

    rows: list[dict[str, Any]] = []
    jobs = _resolve_jobs(int(args.jobs), len(tasks))
    executor_name = "process"
    if jobs <= 1:
        for task in tasks:
            rows.append(_fit_task(**task))
    else:
        try:
            with ProcessPoolExecutor(max_workers=jobs) as ex:
                futures = [ex.submit(_fit_task, **task) for task in tasks]
                for future in as_completed(futures):
                    rows.append(future.result())
        except Exception:
            executor_name = "thread"
            rows = []
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                futures = [ex.submit(_fit_task, **task) for task in tasks]
                for future in as_completed(futures):
                    rows.append(future.result())

    rows.sort(key=lambda row: (int(row["channel"]), int(row["intensity"])))
    summary_out = output_dir / "fit_summary.csv"
    fieldnames = [
        "channel",
        "intensity",
        "histogram_csv",
        "json_path",
        "png_path",
        "status",
        "n_seed_peaks",
        "gaussian_status",
        "gaussian_n_components",
        "gaussian_reduced_chi2",
        "vinogradov_status",
        "vinogradov_reduced_chi2",
        "gain",
        "sigma0",
        "sigma1",
        "vinogradov_snr_ped",
        "vinogradov_snr_combined",
        "mu",
        "lambda",
    ]
    with summary_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    report = {
        "run_dir": str(run_dir),
        "cpp_dir": str(cpp_dir),
        "output_dir": str(output_dir),
        "n_tasks": len(tasks),
        "jobs": jobs,
        "executor": executor_name,
        "max_peaks": int(args.max_peaks),
        "vinogradov_nmax": int(args.vinogradov_nmax),
        "min_component_area_fraction": float(args.min_component_area_fraction),
        "xmin": float(args.xmin),
        "xmax": float(args.xmax),
        "summary_csv": str(summary_out),
        "fits_dir": str(fit_dir),
    }
    (output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    configure_style()
    raise SystemExit(main())
