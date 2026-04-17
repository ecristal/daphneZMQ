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


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build one thumbnail contact sheet per channel from the all-point LED histogram plots."
    )
    ap.add_argument("analysis_dir", help="cpp_snr_scan analysis directory")
    ap.add_argument(
        "--plot-dir",
        default="",
        help="Default: <analysis_dir>/all_point_plots",
    )
    ap.add_argument(
        "--output-dir",
        default="",
        help="Default: <analysis_dir>/channel_contact_sheets",
    )
    ap.add_argument(
        "--columns",
        type=int,
        default=4,
        help="Number of thumbnail columns per sheet",
    )
    return ap.parse_args()


def read_rows(path: Path) -> dict[int, list[dict[str, object]]]:
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            grouped[int(row["channel"])].append(
                {
                    "channel": int(row["channel"]),
                    "intensity": int(row["intensity"]),
                    "snr": float(row["snr"]) if row["snr"] else math.nan,
                    "snr_combined": float(row["snr_combined"]) if row.get("snr_combined", "") else math.nan,
                    "zero_fraction": float(row["zero_fraction"]) if row["zero_fraction"] else math.nan,
                    "ok": row["ok"].strip().lower() == "true",
                }
            )
    for rows in grouped.values():
        rows.sort(key=lambda item: int(item["intensity"]))
    return grouped


def plot_path(plot_dir: Path, channel: int, intensity: int) -> Path:
    return plot_dir / f"ch{channel:02d}" / f"ch{channel:02d}_intensity_{intensity:04d}.png"


def build_sheet(
    channel: int,
    rows: list[dict[str, object]],
    plot_dir: Path,
    output_dir: Path,
    columns: int,
) -> None:
    cols = max(1, int(columns))
    n = len(rows)
    nrows = int(math.ceil(n / cols))
    fig, axes = plt.subplots(nrows, cols, figsize=(4.6 * cols, 3.4 * nrows), squeeze=False)

    for ax in axes.flat:
        ax.set_visible(False)

    for ax, row in zip(axes.flat, rows):
        ax.set_visible(True)
        image_path = plot_path(plot_dir, int(row["channel"]), int(row["intensity"]))
        if image_path.exists():
            img = plt.imread(image_path)
            ax.imshow(img)
        ax.axis("off")
        title = f"LED intensity = {int(row['intensity'])}"
        subtitle = f"P0={float(row['zero_fraction']):.3f}  S/N={float(row['snr']):.2f}"
        if math.isfinite(float(row["snr_combined"])):
            subtitle += f"  S/Nsym={float(row['snr_combined']):.2f}"
        if not bool(row["ok"]):
            subtitle = "fit unavailable"
        ax.set_title(f"{title}\n{subtitle}", fontsize=9.5, pad=7)

    fig.suptitle(
        f"Channel {channel} contact sheet  |  varying parameter: LED intensity",
        fontsize=16,
        y=0.995,
    )
    fig.tight_layout()
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"ch{channel:02d}_contact_sheet"
    fig.savefig(base.with_suffix(".png"), dpi=220)
    fig.savefig(base.with_suffix(".pdf"))
    plt.close(fig)


def main() -> int:
    args = parse_args()
    analysis_dir = Path(args.analysis_dir).expanduser().resolve()
    plot_dir = Path(args.plot_dir).expanduser().resolve() if args.plot_dir else analysis_dir / "all_point_plots"
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else analysis_dir / "channel_contact_sheets"
    grouped = read_rows(analysis_dir / "summary_by_point_channel.csv")
    for channel, rows in sorted(grouped.items()):
        build_sheet(channel, rows, plot_dir, output_dir, int(args.columns))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
