#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colormaps, colors, font_manager

ROOT_DIR = Path(__file__).resolve().parents[1]
CLIENT_DIR = ROOT_DIR / "client"
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

from analyze_waveform_dataset import (  # type: ignore
    compute_avg_fft_dbfs,
    get_window,
    load_channel_waves,
    parse_channels_expr,
)


def preferred_font() -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in ("JetBrains Mono", "IBM Plex Mono", "DejaVu Sans Mono", ".SF NS Mono"):
        if candidate in installed:
            return candidate
    return "monospace"


def configure_style() -> None:
    plt.rcParams.update(
        {
            "figure.figsize": (8.8, 5.2),
            "figure.dpi": 180,
            "savefig.dpi": 220,
            "font.family": preferred_font(),
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3.0,
            "ytick.major.size": 3.0,
        }
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Plot one FFT overlay per channel across vgain points for a dark scan."
    )
    ap.add_argument("run_dir", help="Dark scan directory containing vgain_XXXX point folders")
    ap.add_argument("--output-dir", default="", help="Default: <run_dir>/fft_channel_overlays_vgain")
    ap.add_argument("--channels", default="", help="Channels CSV/range override, e.g. '4-7,12-23'")
    ap.add_argument("-L", type=int, default=0, help="Samples per waveform override")
    ap.add_argument("--fs", type=float, default=0.0, help="Sampling rate override (Hz)")
    ap.add_argument("--max-waves", type=int, default=0, help="Max waveforms loaded per point/channel (0 = all)")
    ap.add_argument("--fft_avg_waves", type=int, default=2000, help="Waveforms averaged per FFT")
    ap.add_argument(
        "--fft_window",
        type=str,
        default="BLACKMAN-HARRIS",
        choices=["NONE", "HANNING", "HAMMING", "BLACKMAN", "BLACKMAN-HARRIS", "TUKEY"],
        help="FFT window",
    )
    ap.add_argument("--fft_full_scale_counts", type=float, default=16384.0, help="Full-scale counts for dBFS")
    ap.add_argument("--fft_keep_dc", action="store_true", help="Keep DC in FFT")
    ap.add_argument("--fft_log_x", action="store_true", help="Use logarithmic frequency axis")
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed")
    ap.add_argument("--overview", action="store_true", help="Also save overview grid pages")
    return ap.parse_args()


def parse_scan_metadata(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def parse_scan_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def discover_points(run_dir: Path) -> list[tuple[int, Path]]:
    points: list[tuple[int, Path]] = []
    for path in sorted(run_dir.glob("vgain_*")):
        if not path.is_dir():
            continue
        try:
            vgain = int(path.name.split("_")[-1])
        except ValueError:
            continue
        points.append((vgain, path))
    if points:
        return points

    points_root = run_dir / "points"
    for path in sorted(points_root.glob("vgain_*")):
        if not path.is_dir():
            continue
        try:
            vgain = int(path.name.split("_")[-1])
        except ValueError:
            continue
        points.append((vgain, path))
    return points


def infer_channels(run_dir: Path, args: argparse.Namespace, manifest: dict, meta: dict[str, str]) -> list[int]:
    if args.channels:
        return parse_channels_expr(args.channels)
    if isinstance(manifest.get("channels"), list):
        return [int(ch) for ch in manifest["channels"]]
    if "channels" in meta:
        return parse_channels_expr(meta["channels"])
    raise ValueError("Channels could not be inferred. Provide --channels.")


def infer_n_samples(args: argparse.Namespace, manifest: dict, meta: dict[str, str]) -> int:
    if args.L > 0:
        return int(args.L)
    if "waveform_len" in meta:
        return int(meta["waveform_len"])
    if "waveform_len" in manifest:
        return int(manifest["waveform_len"])
    raise ValueError("Waveform length could not be inferred. Provide -L.")


def infer_fs(args: argparse.Namespace, manifest: dict) -> float:
    if args.fs > 0:
        return float(args.fs)
    return float(manifest.get("sampling_rate_hz", 62.5e6))


def collect_fft_series(
    points: list[tuple[int, Path]],
    *,
    channels: list[int],
    n_samples: int,
    fs_hz: float,
    fft_window: str,
    fft_avg_waves: int,
    fft_full_scale_counts: float,
    interpret: str,
    max_waves: int,
    keep_dc: bool,
) -> dict[int, list[tuple[int, np.ndarray, np.ndarray, int]]]:
    window = get_window(fft_window, n_samples)
    grouped: dict[int, list[tuple[int, np.ndarray, np.ndarray, int]]] = {ch: [] for ch in channels}
    for vgain, point_dir in points:
        for ch in channels:
            path = point_dir / f"channel_{ch}.dat"
            if not path.exists():
                continue
            waves = load_channel_waves(path, n_samples=n_samples, max_waves=max_waves, interpret=interpret)
            if waves.size == 0:
                continue
            freq_hz, fft_dbfs, used = compute_avg_fft_dbfs(
                waves,
                fs_hz=fs_hz,
                window=window,
                avg_waves=fft_avg_waves,
                full_scale_counts=fft_full_scale_counts,
                remove_dc=(not keep_dc),
            )
            grouped[ch].append((vgain, freq_hz, fft_dbfs, used))
    return grouped


def save_channel_plot(
    channel: int,
    series: list[tuple[int, np.ndarray, np.ndarray, int]],
    *,
    output_dir: Path,
    run_name: str,
    fft_log_x: bool,
    keep_dc: bool,
) -> None:
    fig, ax = plt.subplots(figsize=(9.2, 5.4), constrained_layout=True)
    vgain_values = [item[0] for item in series]
    norm = colors.Normalize(vmin=min(vgain_values), vmax=max(vgain_values))
    cmap = colormaps["viridis"]

    for vgain, freq_hz, fft_dbfs, _used in series:
        k0 = 0 if keep_dc else (4 if freq_hz.size > 4 else 0)
        if fft_log_x:
            k0 = max(k0, 1)
        x = freq_hz[k0:] / 1e6
        y = fft_dbfs[k0:]
        if fft_log_x:
            mask = x > 0
            x = x[mask]
            y = y[mask]
        if x.size == 0:
            continue
        ax.plot(x, y, color=cmap(norm(vgain)), linewidth=1.05, alpha=0.95)

    if fft_log_x:
        ax.set_xscale("log")
    ax.set_title(f"{run_name} | ch{channel:02d} FFT overlay across vgain")
    ax.set_xlabel("Frequency [MHz]" + (" (log)" if fft_log_x else ""))
    ax.set_ylabel("Power [dBFS/bin]")
    ax.grid(True, which="both" if fft_log_x else "major", alpha=0.32)

    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, pad=0.02)
    cbar.set_label("vgain")

    base = output_dir / f"ch{channel:02d}_fft_overlay_vs_vgain"
    fig.savefig(base.with_suffix(".png"))
    fig.savefig(base.with_suffix(".pdf"))
    plt.close(fig)


def save_overview_pages(
    grouped: dict[int, list[tuple[int, np.ndarray, np.ndarray, int]]],
    *,
    output_dir: Path,
    run_name: str,
    fft_log_x: bool,
    keep_dc: bool,
) -> None:
    channels = [ch for ch in sorted(grouped) if grouped[ch]]
    if not channels:
        return

    all_vgains = sorted({item[0] for series in grouped.values() for item in series})
    norm = colors.Normalize(vmin=min(all_vgains), vmax=max(all_vgains))
    cmap = colormaps["viridis"]

    page_size = 4
    page = 0
    for start in range(0, len(channels), page_size):
        subset = channels[start : start + page_size]
        fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.4), constrained_layout=True)
        axes_flat = list(axes.flat)
        for ax, ch in zip(axes_flat, subset):
            for vgain, freq_hz, fft_dbfs, _used in grouped[ch]:
                k0 = 0 if keep_dc else (4 if freq_hz.size > 4 else 0)
                if fft_log_x:
                    k0 = max(k0, 1)
                x = freq_hz[k0:] / 1e6
                y = fft_dbfs[k0:]
                if fft_log_x:
                    mask = x > 0
                    x = x[mask]
                    y = y[mask]
                if x.size == 0:
                    continue
                ax.plot(x, y, color=cmap(norm(vgain)), linewidth=0.9, alpha=0.9)
            if fft_log_x:
                ax.set_xscale("log")
            ax.set_title(f"ch{ch:02d}")
            ax.set_xlabel("MHz")
            ax.set_ylabel("dBFS/bin")
            ax.grid(True, which="both" if fft_log_x else "major", alpha=0.28)
        for ax in axes_flat[len(subset):]:
            ax.axis("off")

        sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=axes_flat, pad=0.01, shrink=0.95)
        cbar.set_label("vgain")
        fig.suptitle(f"{run_name} | FFT overlays by channel across vgain", fontsize=15)

        out = output_dir / f"fft_overlay_overview_page_{page:02d}"
        fig.savefig(out.with_suffix(".png"))
        fig.savefig(out.with_suffix(".pdf"))
        plt.close(fig)
        page += 1


def write_manifest(
    *,
    output_dir: Path,
    run_dir: Path,
    points: list[tuple[int, Path]],
    channels: list[int],
    n_samples: int,
    fs_hz: float,
    args: argparse.Namespace,
) -> None:
    payload = {
        "type": "dark_vgain_fft_channel_overlays",
        "run_dir": str(run_dir),
        "channels": channels,
        "vgain_values": [vgain for vgain, _point in points],
        "waveform_len": n_samples,
        "fs_hz": fs_hz,
        "max_waves": int(args.max_waves),
        "fft_avg_waves": int(args.fft_avg_waves),
        "fft_window": args.fft_window,
        "fft_full_scale_counts": float(args.fft_full_scale_counts),
        "fft_keep_dc": bool(args.fft_keep_dc),
        "fft_log_x": bool(args.fft_log_x),
        "interpret": args.interpret,
    }
    (output_dir / "overlay_manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (run_dir / "fft_channel_overlays_vgain")
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_style()

    manifest = parse_scan_manifest(run_dir / "scan_manifest.json")
    meta = parse_scan_metadata(run_dir / "scan_metadata.txt")
    points = discover_points(run_dir)
    if not points:
        print(f"No vgain points found in {run_dir}", file=sys.stderr)
        return 2

    channels = infer_channels(run_dir, args, manifest, meta)
    n_samples = infer_n_samples(args, manifest, meta)
    fs_hz = infer_fs(args, manifest)

    grouped = collect_fft_series(
        points,
        channels=channels,
        n_samples=n_samples,
        fs_hz=fs_hz,
        fft_window=args.fft_window,
        fft_avg_waves=int(args.fft_avg_waves),
        fft_full_scale_counts=float(args.fft_full_scale_counts),
        interpret=args.interpret,
        max_waves=int(args.max_waves),
        keep_dc=bool(args.fft_keep_dc),
    )

    run_name = run_dir.name
    for ch in channels:
        if grouped.get(ch):
            save_channel_plot(
                ch,
                grouped[ch],
                output_dir=output_dir,
                run_name=run_name,
                fft_log_x=bool(args.fft_log_x),
                keep_dc=bool(args.fft_keep_dc),
            )

    if args.overview:
        save_overview_pages(
            grouped,
            output_dir=output_dir,
            run_name=run_name,
            fft_log_x=bool(args.fft_log_x),
            keep_dc=bool(args.fft_keep_dc),
        )

    write_manifest(
        output_dir=output_dir,
        run_dir=run_dir,
        points=points,
        channels=channels,
        n_samples=n_samples,
        fs_hz=fs_hz,
        args=args,
    )
    print(f"Saved channel FFT overlays to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
