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


HERE = Path(__file__).resolve().parent
SAMPLE_NS = 16.0


def preferred_monospace_font() -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono", ".SF NS Mono"):
        if candidate in installed:
            return candidate
    return "monospace"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Create publication-ready plots for the selected best LED scan point per channel."
    )
    ap.add_argument("analysis_dir", help="cpp_snr_scan output directory")
    ap.add_argument(
        "--output-dir",
        default="",
        help="Default: <analysis_dir>/publication_plots",
    )
    ap.add_argument(
        "--fit-threshold-frac",
        type=float,
        default=0.006,
        help="Fraction of max total fit used to trim the x range",
    )
    ap.add_argument(
        "--count-quantile",
        type=float,
        default=0.998,
        help="Upper cumulative count quantile used to trim the x range",
    )
    ap.add_argument(
        "--max-columns",
        type=int,
        default=4,
        help="Columns for the overview grid",
    )
    ap.add_argument(
        "--all-points",
        action="store_true",
        help="Also render plots for every histogram in summary_by_point_channel.csv",
    )
    return ap.parse_args()


def configure_style() -> None:
    plt.rcParams.update(
        {
            "figure.figsize": (7.2, 4.8),
            "figure.dpi": 180,
            "savefig.dpi": 220,
            "font.family": preferred_monospace_font(),
            "font.size": 12,
            "axes.labelsize": 13,
            "axes.titlesize": 14,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 11,
            "legend.frameon": False,
            "grid.alpha": 0.0,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
        }
    )


def read_rows(csv_path: Path) -> list[dict[str, float | int | str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, float | int | str]] = []
        for row in reader:
            rows.append(
                {
                    "channel": int(row["channel"]),
                    "intensity": int(row["intensity"]),
                    "point_dir": row["point_dir"],
                    "snr": float(row["snr"]),
                    "snr_combined": float(row["snr_combined"]),
                    "zero_fraction": float(row["zero_fraction"]),
                    "selection_score": float(row["selection_score"]),
                    "first_peak_mean": float(row["first_peak_mean"]),
                    "first_peak_sigma": float(row["first_peak_sigma"]),
                    "pedestal_sigma": float(row["pedestal_sigma"]),
                    "sample_sigma": float(row["sample_sigma"]),
                    "n_clean_waveforms": int(row["n_clean_waveforms"]),
                }
            )
        return rows


def read_best_rows(best_csv: Path) -> list[dict[str, float | int | str]]:
    return read_rows(best_csv)


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
        fit_threshold = max(float(np.max(yfit)) * fit_threshold_frac, 1e-9)
        fit_mask = yfit > fit_threshold
        if np.any(fit_mask):
            fit_xmax = float(xfit[np.flatnonzero(fit_mask)[-1]])
    else:
        total_fit = frame["total_fit"].to_numpy(dtype=float)
        fit_threshold = max(float(np.max(total_fit)) * fit_threshold_frac, 1e-9)
        fit_mask = total_fit > fit_threshold
        if np.any(fit_mask):
            fit_xmax = float(x[np.flatnonzero(fit_mask)[-1]])

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


def plot_channel(
    row: dict[str, float | int | str],
    hist_csv: Path,
    output_base: Path,
    fit_threshold_frac: float,
    count_quantile: float,
) -> None:
    frame = pd.read_csv(hist_csv)
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

    fig, ax = plt.subplots()
    ax.step(
        x_plot[mask] * SAMPLE_NS,
        count[mask],
        where="mid",
        color="#4C72B0",
        linewidth=0.72,
        label="Charge histogram",
    )

    ymax = float(np.max(count[mask])) if np.any(mask) else 0.0
    if retro_fit.get("status") == "ok":
        params = retro_fit["params"]
        xfit = np.asarray(retro_fit["xfit"], dtype=float)
        yfit = np.asarray(retro_fit["yfit"], dtype=float)
        fit_mask = (xfit >= xmin_plot) & (xfit <= xmax_plot)
        ax.plot(xfit[fit_mask] * SAMPLE_NS, yfit[fit_mask], color="#1B6CA8", linewidth=1.0, linestyle="--", label="fit")
        comp_colors = ["#C44E52", "#55A868", "#8172B2"]
        for idx, component in enumerate(retro_fit["components"]):
            comp = np.asarray(component, dtype=float)
            if not np.any(comp[fit_mask] > 0):
                continue
            labels = ["Pedestal", "1 p.e.", "2 p.e."]
            ax.plot(
                xfit[fit_mask] * SAMPLE_NS,
                comp[fit_mask],
                color=comp_colors[idx],
                linewidth=0.85,
                linestyle=":",
                alpha=0.95,
                label=labels[idx],
            )
        mu0 = float(params["mu0"]) * SAMPLE_NS
        mu1 = float(params["mu1"]) * SAMPLE_NS
        s0 = float(params["s0"]) * SAMPLE_NS
        s1 = float(params["s1"]) * SAMPLE_NS
        gain = float(params["gain"]) * SAMPLE_NS
        snr_sep = gain / math.sqrt(max(1e-9, s0 * s0 + s1 * s1))
        snr_ped = gain / max(s0, 1e-9)
        ax.axvline(mu0, color="#7F7F7F", linewidth=0.8, linestyle="--")
        ax.axvline(mu1, color="#7F7F7F", linewidth=0.8, linestyle="--")
        ymax = max(ymax, float(np.max(yfit[fit_mask])) if np.any(fit_mask) else 0.0)
        stats_text = (
            f"mu0 = {mu0: .3f} ADC*ns\n"
            f"s0  = {s0: .3f} ADC*ns\n"
            f"mu1 = {mu1: .3f} ADC*ns\n"
            f"s1  = {s1: .3f} ADC*ns\n"
            f"gain = {gain: .3f} ADC*ns\n"
            f"SNR = gain/sqrt(s0^2+s1^2) = {snr_sep: .2f}\n"
            f"alt = gain/s0 = {snr_ped: .2f}"
        )
    else:
        peak_columns = [col for col in frame.columns if col.startswith("peak_")]
        comp_colors = ["#C44E52", "#55A868", "#8172B2", "#CCB974", "#64B5CD", "#E17C05"]
        for idx, col in enumerate(peak_columns):
            component = frame[col].to_numpy(dtype=float)
            if not np.any(component[mask] > 0):
                continue
            ax.plot(
                x_plot[mask] * SAMPLE_NS,
                component[mask],
                color=comp_colors[idx % len(comp_colors)],
                linewidth=0.85,
                linestyle=":",
                alpha=0.9,
                label="C++ components" if idx == 0 else None,
            )
        stats_text = "\n".join(
            [
                "Retro fit failed",
                rf"$P_0 = {float(row['zero_fraction']):.3f}$",
                rf"$\mu_1 \approx {float(row['first_peak_mean']):.0f}$",
                rf"$\sigma_0 \approx {float(row['pedestal_sigma']):.0f}$",
                rf"$N_{{clean}} = {int(row['n_clean_waveforms'])}$",
            ]
        )

    ax.set_xlim(xmin_plot * SAMPLE_NS, xmax_plot * SAMPLE_NS)
    ax.set_ylim(0.0, ymax * 1.18 if ymax > 0 else 1.0)
    ax.set_xlabel("Charge integral [ADC*ns]")
    ax.set_ylabel("Counts")
    ax.grid(False)
    apply_scientific_xaxis(ax)
    ax.set_title(f"Channel {int(row['channel'])}  |  LED intensity {int(row['intensity'])}")

    ax.text(
        0.97,
        0.97,
        stats_text,
        transform=ax.transAxes,
        ha="right",
        va="top",
    )

    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(output_base.with_suffix(".png"))
    fig.savefig(output_base.with_suffix(".pdf"))
    plt.close(fig)


def render_all_point_plots(
    rows: list[dict[str, float | int | str]],
    analysis_dir: Path,
    output_dir: Path,
    fit_threshold_frac: float,
    count_quantile: float,
) -> None:
    hist_dir = analysis_dir / "all_histograms"
    for row in rows:
        hist_csv = hist_dir / (
            f"ch{int(row['channel']):02d}_intensity_{int(row['intensity']):04d}_histogram.csv"
        )
        if not hist_csv.exists():
            continue
        output_base = output_dir / f"ch{int(row['channel']):02d}_intensity_{int(row['intensity']):04d}"
        plot_channel(
            row,
            hist_csv,
            output_base,
            fit_threshold_frac=fit_threshold_frac,
            count_quantile=count_quantile,
        )


def plot_overview(
    rows: list[dict[str, float | int | str]],
    analysis_dir: Path,
    output_dir: Path,
    max_columns: int,
    fit_threshold_frac: float,
    count_quantile: float,
) -> None:
    ncols = max(1, max_columns)
    nrows = int(math.ceil(len(rows) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4.6 * ncols, 3.3 * nrows), squeeze=False)

    for ax in axes.flat:
        ax.set_visible(False)

    for ax, row in zip(axes.flat, rows):
        ax.set_visible(True)
        hist_csv = analysis_dir / (
            f"best_ch{int(row['channel']):02d}_intensity_{int(row['intensity']):04d}_histogram.csv"
        )
        frame = pd.read_csv(hist_csv)
        retro_fit = fit_retro_triple_gauss(
            frame,
            mu1_guess=float(row["first_peak_mean"]),
            sigma0_guess=float(row["pedestal_sigma"]),
            sigma1_guess=float(row["first_peak_sigma"]),
        )
        x = frame["x"].to_numpy(dtype=float)
        count = frame["count"].to_numpy(dtype=float)
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
        ax.step(x_plot[mask] * SAMPLE_NS, count[mask], where="mid", color="#4C72B0", linewidth=0.72)
        if retro_fit.get("status") == "ok":
            xfit = np.asarray(retro_fit["xfit"], dtype=float)
            yfit = np.asarray(retro_fit["yfit"], dtype=float)
            fit_mask = (xfit >= xmin_plot) & (xfit <= xmax_plot)
            ax.plot(xfit[fit_mask] * SAMPLE_NS, yfit[fit_mask], color="#1B6CA8", linewidth=0.95, linestyle="--")
            ax.plot(
                [],
                [],
                color="#1B6CA8",
                linewidth=1.0,
                linestyle="--",
            )
            snr_text = f"{float(row['snr']):.2f}"
        else:
            snr_text = f"{float(row['snr']):.2f}"
        ax.set_title(
            f"ch{int(row['channel'])}  I={int(row['intensity'])}\nS/N={snr_text}  P0={float(row['zero_fraction']):.2f}",
            fontsize=10.5,
        )
        ax.set_xlim(xmin_plot * SAMPLE_NS, xmax_plot * SAMPLE_NS)
        ax.grid(False)
        apply_scientific_xaxis(ax)

    fig.supxlabel("Charge integral [ADC*ns]")
    fig.supylabel("Counts")
    fig.tight_layout()
    fig.savefig(output_dir / "best_points_overview.png")
    fig.savefig(output_dir / "best_points_overview.pdf")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    analysis_dir = Path(args.analysis_dir).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else analysis_dir / "publication_plots"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    best_csv = analysis_dir / "best_by_channel.csv"
    rows = read_best_rows(best_csv)
    configure_style()

    for row in rows:
        hist_csv = analysis_dir / (
            f"best_ch{int(row['channel']):02d}_intensity_{int(row['intensity']):04d}_histogram.csv"
        )
        output_base = output_dir / f"ch{int(row['channel']):02d}_best_intensity_{int(row['intensity']):04d}"
        plot_channel(
            row,
            hist_csv,
            output_base,
            fit_threshold_frac=float(args.fit_threshold_frac),
            count_quantile=float(args.count_quantile),
        )

    plot_overview(
        rows,
        analysis_dir,
        output_dir,
        max_columns=int(args.max_columns),
        fit_threshold_frac=float(args.fit_threshold_frac),
        count_quantile=float(args.count_quantile),
    )
    if args.all_points:
        summary_csv = analysis_dir / "summary_by_point_channel.csv"
        if summary_csv.exists():
            all_rows = read_rows(summary_csv)
            render_all_point_plots(
                all_rows,
                analysis_dir,
                output_dir,
                fit_threshold_frac=float(args.fit_threshold_frac),
                count_quantile=float(args.count_quantile),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
