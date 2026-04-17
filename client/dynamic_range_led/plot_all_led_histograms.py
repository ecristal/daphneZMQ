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


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Create one histogram plot per channel and intensity from cpp_snr_scan outputs."
    )
    ap.add_argument("analysis_dir", help="cpp_snr_scan output directory")
    ap.add_argument(
        "--output-dir",
        default="",
        help="Default: <analysis_dir>/all_point_plots",
    )
    ap.add_argument(
        "--show-total-fit",
        action="store_true",
        help="Also draw the summed fit curve. Off by default because the total fit is often misleading.",
    )
    ap.add_argument(
        "--fit-threshold-frac",
        type=float,
        default=0.006,
        help="Fraction of max component used to trim the x range.",
    )
    ap.add_argument(
        "--count-quantile",
        type=float,
        default=0.998,
        help="Upper cumulative count quantile used to trim the x range.",
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
            "legend.frameon": False,
            "grid.alpha": 0.0,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
        }
    )


def read_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "channel": int(row["channel"]),
                    "intensity": int(row["intensity"]),
                    "point_dir": row["point_dir"],
                    "snr": float(row["snr"]) if row["snr"] not in {"", "nan"} else math.nan,
                    "snr_combined": float(row["snr_combined"]) if row["snr_combined"] not in {"", "nan"} else math.nan,
                    "zero_fraction": float(row["zero_fraction"]) if row["zero_fraction"] not in {"", "nan"} else math.nan,
                    "first_peak_mean": float(row["first_peak_mean"]) if row["first_peak_mean"] not in {"", "nan"} else math.nan,
                    "first_peak_sigma": float(row["first_peak_sigma"]) if row["first_peak_sigma"] not in {"", "nan"} else math.nan,
                    "pedestal_sigma": float(row["pedestal_sigma"]) if row["pedestal_sigma"] not in {"", "nan"} else math.nan,
                    "n_clean_waveforms": int(row["n_clean_waveforms"]),
                    "ok": row["ok"].strip().lower() == "true",
                }
            )
    return rows


def histogram_csv_path(analysis_dir: Path, channel: int, intensity: int) -> Path:
    return analysis_dir / "all_histograms" / f"ch{channel:02d}_intensity_{intensity:04d}_histogram.csv"


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

    xmin = min(-4.5 * pedestal_sigma if np.isfinite(pedestal_sigma) and pedestal_sigma > 0 else x[0],
               float(np.min(x[counts > 0])) if np.any(counts > 0) else x[0])

    peak_xmax = float(np.max(x))
    if retro_fit and retro_fit.get("status") == "ok":
        xfit = np.asarray(retro_fit["xfit"], dtype=float)
        yfit = np.asarray(retro_fit["yfit"], dtype=float)
        threshold = max(float(np.max(yfit)) * fit_threshold_frac, 1e-9)
        mask = yfit > threshold
        if np.any(mask):
            peak_xmax = float(xfit[np.flatnonzero(mask)[-1]])
    else:
        peak_columns = [c for c in frame.columns if c.startswith("peak_")]
        if peak_columns:
            comp_max = np.zeros_like(x, dtype=float)
            for col in peak_columns:
                comp_max = np.maximum(comp_max, frame[col].to_numpy(dtype=float))
            threshold = max(float(np.max(comp_max)) * fit_threshold_frac, 1e-9)
            mask = comp_max > threshold
            if np.any(mask):
                peak_xmax = float(x[np.flatnonzero(mask)[-1]])

    if np.sum(counts) > 0:
        cum = np.cumsum(np.clip(counts, 0.0, None)) / np.sum(np.clip(counts, 0.0, None))
        idx = int(np.searchsorted(cum, count_quantile))
        idx = min(max(idx, 0), len(x) - 1)
        count_xmax = float(x[idx])
    else:
        count_xmax = float(np.max(x))

    if np.isfinite(first_peak_mean) and first_peak_mean > 0:
        desired = 6.2 * first_peak_mean
    else:
        desired = count_xmax
    xmin = max(float(xmin), -2000.0)
    xmax = min(max(count_xmax, peak_xmax, desired), float(np.max(x)))
    return xmin, xmax


def make_plot(
    row: dict[str, object],
    frame: pd.DataFrame,
    out_png: Path,
    out_pdf: Path,
    show_total_fit: bool,
    fit_threshold_frac: float,
    count_quantile: float,
) -> None:
    x = frame["x"].to_numpy(dtype=float)
    counts = frame["count"].to_numpy(dtype=float)
    retro_fit = fit_retro_triple_gauss(
        frame,
        mu1_guess=float(row["first_peak_mean"]) if np.isfinite(float(row["first_peak_mean"])) else max(float(row["pedestal_sigma"]) * 3.0, 1.0),
        sigma0_guess=float(row["pedestal_sigma"]) if np.isfinite(float(row["pedestal_sigma"])) else 1.0,
        sigma1_guess=float(row["first_peak_sigma"]) if np.isfinite(float(row["first_peak_sigma"])) else None,
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
        counts[mask],
        where="mid",
        color="#4C72B0",
        linewidth=0.72,
        label="Charge histogram",
    )
    ymax = float(np.max(counts[mask])) if np.any(mask) else 0.0
    if retro_fit.get("status") == "ok":
        params = retro_fit["params"]
        xfit = np.asarray(retro_fit["xfit"], dtype=float)
        yfit = np.asarray(retro_fit["yfit"], dtype=float)
        fit_mask = (xfit >= xmin_plot) & (xfit <= xmax_plot)
        colors = ["#C44E52", "#55A868", "#8172B2"]
        labels = ["Pedestal", "1 p.e.", "2 p.e."]
        for idx, comp in enumerate(retro_fit["components"]):
            comp_arr = np.asarray(comp, dtype=float)
            if not np.any(comp_arr[fit_mask] > 0):
                continue
            ax.plot(
                xfit[fit_mask] * SAMPLE_NS,
                comp_arr[fit_mask],
                color=colors[idx],
                linestyle=":",
                linewidth=0.85,
                alpha=0.95,
                label=labels[idx],
            )
        if show_total_fit:
            ax.plot(xfit[fit_mask] * SAMPLE_NS, yfit[fit_mask], color="#1B6CA8", linewidth=1.05, alpha=0.9, linestyle="--", label="fit")
        ymax = max(ymax, float(np.max(yfit[fit_mask])) if np.any(fit_mask) else 0.0)

    ax.set_xlim(xmin_plot * SAMPLE_NS, xmax_plot * SAMPLE_NS)
    ax.set_ylim(0.0, ymax * 1.18 if ymax > 0 else 1.0)
    ax.set_xlabel("Charge integral [ADC*ns]")
    ax.set_ylabel("Counts")
    ax.grid(False)
    apply_scientific_xaxis(ax)
    ax.set_title(f"Channel {int(row['channel'])}  |  LED intensity {int(row['intensity'])}")

    if bool(row["ok"]):
        if retro_fit.get("status") == "ok":
            mu0 = float(params["mu0"]) * SAMPLE_NS
            mu1 = float(params["mu1"]) * SAMPLE_NS
            s0 = float(params["s0"]) * SAMPLE_NS
            s1 = float(params["s1"]) * SAMPLE_NS
            gain = float(params["gain"]) * SAMPLE_NS
            snr_sep = gain / math.sqrt(max(1e-9, s0 * s0 + s1 * s1))
            snr_ped = gain / max(s0, 1e-9)
            stats = (
                f"mu0 = {mu0: .3f} ADC*ns\n"
                f"s0  = {s0: .3f} ADC*ns\n"
                f"mu1 = {mu1: .3f} ADC*ns\n"
                f"s1  = {s1: .3f} ADC*ns\n"
                f"gain = {gain: .3f} ADC*ns\n"
                f"SNR = gain/sqrt(s0^2+s1^2) = {snr_sep: .2f}\n"
                f"alt = gain/s0 = {snr_ped: .2f}"
            )
        else:
            stats = "\n".join(
                [
                    "Retro fit failed",
                    rf"$S/N = {float(row['snr']):.2f}$",
                    rf"$S/N_{{sym}} = {float(row['snr_combined']):.2f}$",
                    rf"$P_0 = {float(row['zero_fraction']):.3f}$",
                ]
            )
    else:
        stats = "\n".join(
            [
                "Fit unavailable",
                rf"$\sigma_0 = {float(row['pedestal_sigma']):.0f}$",
                rf"$N_{{clean}} = {int(row['n_clean_waveforms'])}$",
            ]
        )

    ax.text(
        0.97,
        0.97,
        stats,
        transform=ax.transAxes,
        ha="right",
        va="top",
    )
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(out_png)
    fig.savefig(out_pdf)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    analysis_dir = Path(args.analysis_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else analysis_dir / "all_point_plots"
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_style()

    rows = read_rows(analysis_dir / "summary_by_point_channel.csv")
    for row in rows:
        ch = int(row["channel"])
        intensity = int(row["intensity"])
        hist_path = histogram_csv_path(analysis_dir, ch, intensity)
        if not hist_path.exists():
            continue
        frame = pd.read_csv(hist_path)
        ch_dir = output_dir / f"ch{ch:02d}"
        ch_dir.mkdir(parents=True, exist_ok=True)
        base = ch_dir / f"ch{ch:02d}_intensity_{intensity:04d}"
        make_plot(
            row,
            frame,
            base.with_suffix(".png"),
            base.with_suffix(".pdf"),
            show_total_fit=bool(args.show_total_fit),
            fit_threshold_frac=float(args.fit_threshold_frac),
            count_quantile=float(args.count_quantile),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
