#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from plot_all_led_histograms import (
    apply_scientific_xaxis,
    choose_xlim,
    configure_style,
    histogram_csv_path,
)
from retro_charge_fit import fit_retro_triple_gauss


SAMPLE_NS = 16.0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build fully vectorized per-channel LED histogram contact sheets."
    )
    ap.add_argument("analysis_dir", help="cpp_snr_scan analysis directory")
    ap.add_argument(
        "--output-dir",
        default="",
        help="Default: <analysis_dir>/channel_contact_sheets_vector",
    )
    ap.add_argument(
        "--columns",
        type=int,
        default=2,
        help="Number of columns per sheet",
    )
    ap.add_argument(
        "--show-total-fit",
        action="store_true",
        help="Also draw the total fit curve.",
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
    ap.add_argument(
        "--mu1-min",
        type=float,
        default=0.0,
        help="If > 0, highlight panels with fitted mu1 below this value.",
    )
    ap.add_argument(
        "--mu1-max",
        type=float,
        default=0.0,
        help="If > 0, highlight panels with fitted mu1 above this value.",
    )
    return ap.parse_args()


def read_rows(path: Path) -> dict[int, list[dict[str, object]]]:
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            grouped[int(row["channel"])].append(
                {
                    "channel": int(row["channel"]),
                    "intensity": int(row["intensity"]),
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
    for rows in grouped.values():
        rows.sort(key=lambda item: int(item["intensity"]))
    return grouped


def make_panel(
    ax: plt.Axes,
    *,
    analysis_dir: Path,
    row: dict[str, object],
    show_total_fit: bool,
    fit_threshold_frac: float,
    count_quantile: float,
    mu1_min: float,
    mu1_max: float,
) -> None:
    ch = int(row["channel"])
    intensity = int(row["intensity"])
    frame = pd.read_csv(histogram_csv_path(analysis_dir, ch, intensity))
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

    mu1_fit = math.nan
    if retro_fit.get("status") == "ok":
        mu1_fit = float(retro_fit["params"]["mu1"] - retro_fit["params"]["mu0"])

    x_plot = x
    xmin_plot = xmin
    xmax_plot = xmax
    mask = (x_plot >= xmin_plot) & (x_plot <= xmax_plot)

    ax.step(
        x_plot[mask] * SAMPLE_NS,
        counts[mask],
        where="mid",
        color="#4C72B0",
        linewidth=0.72,
    )

    ymax = float(np.max(counts[mask])) if np.any(mask) else 1.0
    if retro_fit.get("status") == "ok":
        xfit = np.asarray(retro_fit["xfit"], dtype=float)
        yfit = np.asarray(retro_fit["yfit"], dtype=float)
        fit_mask = (xfit >= xmin_plot) & (xfit <= xmax_plot)
        colors = ["#C44E52", "#55A868", "#8172B2"]
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
            )
        if show_total_fit:
            ax.plot(
                xfit[fit_mask] * SAMPLE_NS,
                yfit[fit_mask],
                color="#1B6CA8",
                linewidth=0.95,
                linestyle="--",
                alpha=0.9,
            )
        ymax = max(ymax, float(np.max(yfit[fit_mask])) if np.any(fit_mask) else ymax)

    ax.set_xlim(xmin_plot * SAMPLE_NS, xmax_plot * SAMPLE_NS)
    ax.set_ylim(0.0, ymax * 1.12 if ymax > 0 else 1.0)
    ax.grid(False)
    apply_scientific_xaxis(ax)

    title = f"I={intensity}"
    if np.isfinite(mu1_fit):
        title += f"  mu1={mu1_fit:.0f}"
    ax.set_title(title, fontsize=10.5, pad=6)

    stats = f"S/N={float(row['snr']):.2f}  P0={float(row['zero_fraction']):.3f}"
    if np.isfinite(float(row["snr_combined"])):
        stats += f"\nS/Nsym={float(row['snr_combined']):.2f}"
    if np.isfinite(mu1_fit) and ((mu1_min > 0 and mu1_fit < mu1_min) or (mu1_max > 0 and mu1_fit > mu1_max)):
        stats += "\nmu1 out of range"
        for spine in ax.spines.values():
            spine.set_visible(True)
            spine.set_color("#C44E52")
            spine.set_linewidth(1.2)
    ax.text(
        0.98,
        0.98,
        stats,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8.8,
    )


def build_sheet(
    *,
    analysis_dir: Path,
    channel: int,
    rows: list[dict[str, object]],
    output_dir: Path,
    columns: int,
    show_total_fit: bool,
    fit_threshold_frac: float,
    count_quantile: float,
    mu1_min: float,
    mu1_max: float,
) -> None:
    cols = max(1, int(columns))
    nrows = int(math.ceil(len(rows) / cols))
    fig, axes = plt.subplots(nrows, cols, figsize=(6.0 * cols, 4.2 * nrows), squeeze=False)

    for ax in axes.flat:
        ax.set_visible(False)

    for ax, row in zip(axes.flat, rows):
        ax.set_visible(True)
        make_panel(
            ax,
            analysis_dir=analysis_dir,
            row=row,
            show_total_fit=show_total_fit,
            fit_threshold_frac=fit_threshold_frac,
            count_quantile=count_quantile,
            mu1_min=mu1_min,
            mu1_max=mu1_max,
        )

    fig.supxlabel("Charge integral [ADC*ns]")
    fig.supylabel("Counts")
    fig.suptitle(f"Channel {channel} vector contact sheet", fontsize=16, y=0.995)
    fig.tight_layout()

    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"ch{channel:02d}_vector_contact_sheet"
    fig.savefig(base.with_suffix(".pdf"))
    fig.savefig(base.with_suffix(".png"), dpi=220)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    analysis_dir = Path(args.analysis_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else analysis_dir / "channel_contact_sheets_vector"
    configure_style()

    grouped = read_rows(analysis_dir / "summary_by_point_channel.csv")
    for channel, rows in sorted(grouped.items()):
        build_sheet(
            analysis_dir=analysis_dir,
            channel=channel,
            rows=rows,
            output_dir=output_dir,
            columns=int(args.columns),
            show_total_fit=bool(args.show_total_fit),
            fit_threshold_frac=float(args.fit_threshold_frac),
            count_quantile=float(args.count_quantile),
            mu1_min=float(args.mu1_min),
            mu1_max=float(args.mu1_max),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
