#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.ticker import ScalarFormatter

from retro_charge_fit import fit_retro_triple_gauss


SAMPLE_NS = 16.0


def preferred_monospace_font() -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono", ".SF NS Mono"):
        if candidate in installed:
            return candidate
    return "monospace"


def configure_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 180,
            "savefig.dpi": 220,
            "font.family": preferred_monospace_font(),
            "font.size": 10,
            "axes.labelsize": 10,
            "axes.titlesize": 11,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
        }
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build a true vector best-point summary sheet directly from histogram CSV and fit data."
    )
    ap.add_argument("output_base", help="Output path without suffix")
    ap.add_argument("analysis_dirs", nargs="+", help="cpp_snr_scan analysis directories")
    ap.add_argument("--title", default="Best-point summary", help="Sheet title")
    ap.add_argument("--columns", type=int, default=2, help="Number of columns")
    ap.add_argument("--fit-threshold-frac", type=float, default=0.006)
    ap.add_argument("--count-quantile", type=float, default=0.998)
    return ap.parse_args()


def load_best_rows(analysis_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with (analysis_dir / "best_by_channel.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                {
                    "analysis_dir": analysis_dir,
                    "channel": int(row["channel"]),
                    "intensity": int(row["intensity"]),
                    "zero_fraction": float(row["zero_fraction"]),
                    "snr": float(row["snr"]),
                    "snr_combined": float(row["snr_combined"]),
                    "first_peak_mean": float(row["first_peak_mean"]),
                    "first_peak_sigma": float(row["first_peak_sigma"]),
                    "pedestal_sigma": float(row["pedestal_sigma"]),
                }
            )
    rows.sort(key=lambda row: int(row["channel"]))
    return rows


def histogram_path(analysis_dir: Path, channel: int, intensity: int) -> Path:
    return analysis_dir / f"best_ch{channel:02d}_intensity_{intensity:04d}_histogram.csv"


def apply_scientific_xaxis(ax: plt.Axes) -> None:
    formatter = ScalarFormatter(useMathText=True)
    formatter.set_scientific(True)
    formatter.set_powerlimits((0, 0))
    ax.xaxis.set_major_formatter(formatter)


def choose_xlim(
    frame: pd.DataFrame,
    first_peak_mean: float,
    pedestal_sigma: float,
    fit_threshold_frac: float,
    count_quantile: float,
    retro_fit: dict[str, object] | None = None,
) -> tuple[float, float]:
    x = frame["x"].to_numpy(dtype=float)
    counts = frame["count"].to_numpy(dtype=float)

    xmin = min(-4.5 * pedestal_sigma, float(np.min(x[counts > 0])) if np.any(counts > 0) else x[0])
    fit_xmax = float(np.max(x))
    if retro_fit and retro_fit.get("status") == "ok":
        xfit = np.asarray(retro_fit["xfit"], dtype=float)
        yfit = np.asarray(retro_fit["yfit"], dtype=float)
        threshold = max(float(np.max(yfit)) * fit_threshold_frac, 1e-9)
        mask = yfit > threshold
        if np.any(mask):
            fit_xmax = float(xfit[np.flatnonzero(mask)[-1]])

    positive_counts = np.clip(counts, 0.0, None)
    if np.sum(positive_counts) > 0:
        cum = np.cumsum(positive_counts) / np.sum(positive_counts)
        idx = int(np.searchsorted(cum, count_quantile))
        idx = min(max(idx, 0), len(x) - 1)
        count_xmax = float(x[idx])
    else:
        count_xmax = float(np.max(x))

    peak_xmax = max(5.8 * first_peak_mean, 3.0 * first_peak_mean + 4.0 * pedestal_sigma)
    xmin = max(float(xmin), -2000.0)
    xmax = min(max(fit_xmax, count_xmax, peak_xmax), float(np.max(x)))
    return xmin, xmax


def plot_panel(
    ax: plt.Axes,
    row: dict[str, object],
    fit_threshold_frac: float,
    count_quantile: float,
) -> None:
    frame = pd.read_csv(histogram_path(Path(row["analysis_dir"]), int(row["channel"]), int(row["intensity"])))
    x = frame["x"].to_numpy(dtype=float)
    count = frame["count"].to_numpy(dtype=float)
    retro_fit = fit_retro_triple_gauss(
        frame,
        mu1_guess=float(row["first_peak_mean"]),
        sigma0_guess=float(row["pedestal_sigma"]),
        sigma1_guess=float(row["first_peak_sigma"]),
    )
    xmin, xmax = choose_xlim(
        frame,
        first_peak_mean=float(row["first_peak_mean"]),
        pedestal_sigma=float(row["pedestal_sigma"]),
        fit_threshold_frac=fit_threshold_frac,
        count_quantile=count_quantile,
        retro_fit=retro_fit,
    )

    x_plot = x
    xmin_plot = xmin
    xmax_plot = xmax
    mask = (x_plot >= xmin_plot) & (x_plot <= xmax_plot)

    ax.step(
        x_plot[mask] * SAMPLE_NS,
        count[mask],
        where="mid",
        color="#4C72B0",
        linewidth=0.72,
    )

    ymax = float(np.max(count[mask])) if np.any(mask) else 0.0
    if retro_fit.get("status") == "ok":
        params = retro_fit["params"]
        xfit = np.asarray(retro_fit["xfit"], dtype=float)
        yfit = np.asarray(retro_fit["yfit"], dtype=float)
        fit_mask = (xfit >= xmin_plot) & (xfit <= xmax_plot)
        ax.plot(xfit[fit_mask] * SAMPLE_NS, yfit[fit_mask], color="#1B6CA8", linewidth=0.9, linestyle="--")
        colors = ["#C44E52", "#55A868", "#8172B2"]
        for idx, component in enumerate(retro_fit["components"]):
            comp = np.asarray(component, dtype=float)
            if not np.any(comp[fit_mask] > 0):
                continue
            ax.plot(
                xfit[fit_mask] * SAMPLE_NS,
                comp[fit_mask],
                color=colors[idx],
                linewidth=0.75,
                linestyle=":",
                alpha=0.95,
            )
        ymax = max(ymax, float(np.max(yfit[fit_mask])) if np.any(fit_mask) else 0.0)

    ax.set_xlim(xmin_plot * SAMPLE_NS, xmax_plot * SAMPLE_NS)
    ax.set_ylim(0.0, ymax * 1.16 if ymax > 0 else 1.0)
    ax.grid(False)
    apply_scientific_xaxis(ax)
    ax.set_xlabel("Charge integral [ADC*ns]")
    ax.set_ylabel("Counts")
    ax.set_title(f"ch{int(row['channel'])}  I={int(row['intensity'])}\nP0={float(row['zero_fraction']):.3f}", pad=8)
    if retro_fit.get("status") == "ok":
        mu0 = float(params["mu0"]) * SAMPLE_NS
        mu1 = float(params["mu1"]) * SAMPLE_NS
        s0 = float(params["s0"]) * SAMPLE_NS
        s1 = float(params["s1"]) * SAMPLE_NS
        gain = float(params["gain"]) * SAMPLE_NS
        snr_sep = gain / math.sqrt(max(1e-9, s0 * s0 + s1 * s1))
        snr_ped = gain / max(s0, 1e-9)
        stats_text = (
            f"mu0 = {mu0: .2f} ADC*ns\n"
            f"s0  = {s0: .2f} ADC*ns\n"
            f"mu1 = {mu1: .2f} ADC*ns\n"
            f"s1  = {s1: .2f} ADC*ns\n"
            f"gain = {gain: .2f} ADC*ns\n"
            f"SNR = gain/sqrt(s0^2+s1^2) = {snr_sep: .2f}\n"
            f"alt = gain/s0 = {snr_ped: .2f}"
        )
    else:
        stats_text = (
            f"mu0 = {0.0: .2f} ADC*ns\n"
            f"s0  = {float(row['pedestal_sigma']) * SAMPLE_NS: .2f} ADC*ns\n"
            f"mu1 = {float(row['first_peak_mean']) * SAMPLE_NS: .2f} ADC*ns\n"
            f"s1  = {float(row['first_peak_sigma']) * SAMPLE_NS: .2f} ADC*ns\n"
            f"SNR = (mu1-mu0)/sqrt(s0^2+s1^2) = "
            f"{float(row.get('snr_combined', float('nan'))): .2f}\n"
            f"alt = (mu1-mu0)/s0 = {float(row.get('snr', float('nan'))): .2f}"
        )
    ax.text(
        0.98,
        0.98,
        stats_text,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8.6,
    )


def main() -> int:
    args = parse_args()
    configure_style()

    analysis_dirs = [Path(p).expanduser().resolve() for p in args.analysis_dirs]
    output_base = Path(args.output_base).expanduser().resolve()

    rows: list[dict[str, object]] = []
    for analysis_dir in analysis_dirs:
        rows.extend(load_best_rows(analysis_dir))
    rows.sort(key=lambda row: int(row["channel"]))

    cols = max(1, int(args.columns))
    nrows = int(math.ceil(len(rows) / cols))
    fig, axes = plt.subplots(nrows, cols, figsize=(6.3 * cols, 4.9 * nrows), squeeze=False)

    for ax in axes.flat:
        ax.set_visible(False)

    for ax, row in zip(axes.flat, rows):
        ax.set_visible(True)
        plot_panel(ax, row, float(args.fit_threshold_frac), float(args.count_quantile))

    fig.suptitle(args.title, fontsize=18, y=0.995)
    fig.tight_layout()
    output_base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_base.with_suffix(".png"), dpi=220)
    fig.savefig(output_base.with_suffix(".pdf"))
    plt.close(fig)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
