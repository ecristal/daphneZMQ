#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


def preferred_monospace_font() -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono", ".SF NS Mono"):
        if candidate in installed:
            return candidate
    return "monospace"


def configure_style() -> None:
    plt.rcParams.update(
        {
            "figure.figsize": (7.4, 4.8),
            "figure.dpi": 180,
            "savefig.dpi": 220,
            "font.family": preferred_monospace_font(),
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 12,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 9,
            "legend.frameon": False,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
        }
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Plot S/N vs attenuator setting for each channel.")
    ap.add_argument("analysis_dir", help="cpp_snr_scan output directory")
    ap.add_argument(
        "--output-dir",
        default="",
        help="Default: <analysis_dir>/snr_vs_attenuators",
    )
    ap.add_argument(
        "--x-label",
        default="Attenuators",
        help="X-axis label. Default: Attenuators",
    )
    ap.add_argument(
        "--title-prefix",
        default="",
        help="Optional short title prefix added before the channel label.",
    )
    ap.add_argument(
        "--fit-summary-csv",
        default="",
        help="Optional fit_summary.csv from fit_cpp_histograms_parallel.py. Default autodetects under analysis_dir.",
    )
    ap.add_argument(
        "--show-best-marker",
        action="store_true",
        help="Draw the selected best attenuator as a vertical line.",
    )
    return ap.parse_args()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def resolve_fit_summary_csv(analysis_dir: Path, explicit: str) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.exists() else None
    candidates = [
        analysis_dir / "vinogradov_reanalysis_parallel" / "fit_summary.csv",
        analysis_dir / "fit_summary.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def load_channel_led_map(analysis_dir: Path) -> dict[int, int]:
    best_rows = read_csv_rows(analysis_dir / "best_by_channel.csv")
    if not best_rows:
        return {}
    point_dir = Path(best_rows[0]["point_dir"]).resolve()
    manifest = point_dir.parents[2] / "scan_manifest.json"
    if not manifest.exists():
        return {}
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    raw_map = payload.get("channel_to_led_intensity", {})
    out: dict[int, int] = {}
    for key, value in raw_map.items():
        out[int(key)] = int(value)
    return out


def load_fit_lookup(path: Path | None) -> dict[tuple[int, int], dict[str, float | str]]:
    if path is None or not path.exists():
        return {}
    out: dict[tuple[int, int], dict[str, float | str]] = {}
    for row in read_csv_rows(path):
        key = (int(row["channel"]), int(row["intensity"]))
        out[key] = {
            "vinogradov_status": row.get("vinogradov_status", ""),
            "vinogradov_snr_ped": float(row.get("vinogradov_snr_ped", "nan")),
            "vinogradov_snr_combined": float(row.get("vinogradov_snr_combined", "nan")),
            "vinogradov_gain": float(row.get("gain", "nan")),
            "vinogradov_sigma0": float(row.get("sigma0", "nan")),
            "vinogradov_sigma1": float(row.get("sigma1", "nan")),
        }
    return out


def group_rows_by_channel(
    rows: list[dict[str, str]],
    fit_lookup: dict[tuple[int, int], dict[str, float | str]],
) -> dict[int, list[dict[str, float | int | str]]]:
    grouped: dict[int, list[dict[str, float | int | str]]] = {}
    for row in rows:
        channel = int(row["channel"])
        intensity = int(row["intensity"])
        fit_row = fit_lookup.get((channel, intensity), {})
        grouped.setdefault(channel, []).append(
            {
                "channel": channel,
                "intensity": intensity,
                "snr": float(row["snr"]),
                "snr_combined": float(row["snr_combined"]),
                "gain": float(row["first_peak_mean"]),
                "zero_fraction": float(row["zero_fraction"]),
                "n_clean_waveforms": int(row["n_clean_waveforms"]),
                "vinogradov_status": str(fit_row.get("vinogradov_status", "")),
                "vinogradov_snr_ped": float(fit_row.get("vinogradov_snr_ped", math.nan)),
                "vinogradov_snr_combined": float(fit_row.get("vinogradov_snr_combined", math.nan)),
                "vinogradov_gain": float(fit_row.get("vinogradov_gain", math.nan)),
            }
        )
    for channel in grouped:
        grouped[channel].sort(key=lambda item: int(item["intensity"]))
    return grouped


def best_lookup(rows: list[dict[str, str]]) -> dict[int, int]:
    out: dict[int, int] = {}
    for row in rows:
        out[int(row["channel"])] = int(row["intensity"])
    return out


def build_title(prefix: str, channel: int, led_map: dict[int, int]) -> str:
    parts: list[str] = []
    if prefix:
        parts.append(prefix.strip())
    parts.append(f"Channel {channel}")
    led_intensity = led_map.get(channel)
    if led_intensity is not None:
        parts.append(f"LED {led_intensity}")
    return " | ".join(parts)


def plot_channel(
    channel: int,
    rows: list[dict[str, float | int | str]],
    output_dir: Path,
    x_label: str,
    title_prefix: str,
    led_map: dict[int, int],
    best_vgain: int | None,
    show_best_marker: bool,
) -> None:
    x = [int(row["intensity"]) for row in rows]
    y_ped = [float(row["snr"]) for row in rows]
    y_combined = [float(row["snr_combined"]) for row in rows]
    y_gain = [float(row["gain"]) for row in rows]
    y_vin_ped = [float(row["vinogradov_snr_ped"]) for row in rows]
    y_vin_combined = [float(row["vinogradov_snr_combined"]) for row in rows]
    y_vin_gain = [float(row["vinogradov_gain"]) for row in rows]

    fig, ax = plt.subplots()
    ax.plot(
        x,
        y_ped,
        color="#C44E52",
        marker="o",
        markersize=2.8,
        linewidth=0.95,
        linestyle=":",
        alpha=0.75,
        label="Quick S/N pedestal",
    )
    ax.plot(
        x,
        y_combined,
        color="#1B6CA8",
        marker="s",
        markersize=2.7,
        linewidth=0.95,
        linestyle=":",
        alpha=0.75,
        label="Quick S/N combined",
    )
    finite_vin_ped = [(xi, yi) for xi, yi in zip(x, y_vin_ped) if math.isfinite(yi)]
    finite_vin_combined = [(xi, yi) for xi, yi in zip(x, y_vin_combined) if math.isfinite(yi)]
    if finite_vin_ped:
        ax.plot(
            [xi for xi, _ in finite_vin_ped],
            [yi for _, yi in finite_vin_ped],
            color="#DD8452",
            marker="o",
            markersize=3.4,
            linewidth=1.25,
            label="Vin S/N pedestal",
        )
    if finite_vin_combined:
        ax.plot(
            [xi for xi, _ in finite_vin_combined],
            [yi for _, yi in finite_vin_combined],
            color="#55A868",
            marker="D",
            markersize=3.2,
            linewidth=1.25,
            label="Vin S/N combined",
        )
    if show_best_marker and best_vgain is not None:
        ax.axvline(best_vgain, color="#7F7F7F", linewidth=0.8, linestyle="--", alpha=0.85, label=f"best = {best_vgain}")
    ax.set_xlabel(x_label)
    ax.set_ylabel("Signal / Noise")
    ax.set_title(build_title(title_prefix, channel, led_map), fontsize=11)
    ax.set_xlim(min(x) - 25, max(x) + 25)

    snr_values = [value for value in (y_ped + y_combined + y_vin_ped + y_vin_combined) if math.isfinite(value)]
    ymax = max(snr_values) if snr_values else 1.0
    ax.set_ylim(bottom=0.0, top=max(1.0, ymax * 1.12))

    ax_gain = ax.twinx()
    gain_values = y_vin_gain if any(math.isfinite(value) for value in y_vin_gain) else y_gain
    gain_label = "Gain (Vin)" if any(math.isfinite(value) for value in y_vin_gain) else "Gain"
    ax_gain.plot(
        x,
        gain_values,
        color="#8172B2",
        marker="^",
        markersize=3.2,
        linewidth=1.1,
        linestyle="--",
        label=gain_label,
    )
    ax_gain.set_ylabel("Gain [a.u.]")
    ax_gain.set_ylim(bottom=0.0)

    lines = ax.get_lines() + ax_gain.get_lines()
    labels = [line.get_label() for line in lines]
    ax.legend(lines, labels, loc="upper right")

    fig.tight_layout()
    base = output_dir / f"ch{channel:02d}_snr_vs_attenuators"
    fig.savefig(base.with_suffix(".pdf"))
    fig.savefig(base.with_suffix(".png"))
    plt.close(fig)


def plot_overview(
    grouped: dict[int, list[dict[str, float | int | str]]],
    output_dir: Path,
    x_label: str,
    led_map: dict[int, int],
    best_by_channel: dict[int, int],
    show_best_marker: bool,
) -> None:
    channels = sorted(grouped)
    fig, axes = plt.subplots(len(channels), 1, figsize=(8.0, 2.5 * len(channels)), sharex=True)
    if len(channels) == 1:
        axes = [axes]

    for ax, channel in zip(axes, channels):
        rows = grouped[channel]
        x = [int(row["intensity"]) for row in rows]
        y_combined = [float(row["snr_combined"]) for row in rows]
        y_vin_combined = [float(row["vinogradov_snr_combined"]) for row in rows]
        ax.plot(
            x,
            y_combined,
            color="#1B6CA8",
            marker="s",
            markersize=2.4,
            linewidth=0.95,
            linestyle=":",
            alpha=0.75,
            label="Quick combined",
        )
        finite_vin = [(xi, yi) for xi, yi in zip(x, y_vin_combined) if math.isfinite(yi)]
        if finite_vin:
            ax.plot(
                [xi for xi, _ in finite_vin],
                [yi for _, yi in finite_vin],
                color="#55A868",
                marker="D",
                markersize=2.5,
                linewidth=1.05,
                label="Vin combined",
            )
        best_vgain = best_by_channel.get(channel)
        if show_best_marker and best_vgain is not None:
            ax.axvline(best_vgain, color="#7F7F7F", linewidth=0.8, linestyle="--", alpha=0.85)
        led_text = f", LED {led_map[channel]}" if channel in led_map else ""
        ax.set_ylabel(f"ch{channel}{led_text}")
        ax.set_ylim(bottom=0.0)

    axes[0].legend(loc="upper right", ncol=2)
    axes[-1].set_xlabel(x_label)
    fig.suptitle("Signal / Noise vs Attenuators", fontsize=12)
    fig.tight_layout()
    fig.savefig(output_dir / "snr_vs_attenuators_overview.pdf")
    fig.savefig(output_dir / "snr_vs_attenuators_overview.png")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    analysis_dir = Path(args.analysis_dir).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else analysis_dir / "snr_vs_attenuators"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    configure_style()
    summary_rows = read_csv_rows(analysis_dir / "summary_by_point_channel.csv")
    best_rows = read_csv_rows(analysis_dir / "best_by_channel.csv")
    fit_lookup = load_fit_lookup(resolve_fit_summary_csv(analysis_dir, args.fit_summary_csv))
    grouped = group_rows_by_channel(summary_rows, fit_lookup)
    best_by_channel = best_lookup(best_rows)
    led_map = load_channel_led_map(analysis_dir)

    for channel in sorted(grouped):
        plot_channel(
            channel=channel,
            rows=grouped[channel],
            output_dir=output_dir,
            x_label=args.x_label,
            title_prefix=args.title_prefix,
            led_map=led_map,
            best_vgain=best_by_channel.get(channel),
            show_best_marker=args.show_best_marker,
        )
    plot_overview(grouped, output_dir, args.x_label, led_map, best_by_channel, args.show_best_marker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
