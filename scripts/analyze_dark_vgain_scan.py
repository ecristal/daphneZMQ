#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
ANALYZER = ROOT_DIR / "client" / "analyze_waveform_dataset.py"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run FFT/metrics analysis across all vgain points in a dark scan.")
    ap.add_argument("run_dir", help="Dark scan directory containing vgain_XXXX point folders")
    ap.add_argument("--channels", default="", help="Channel CSV/range override. Default: read scan metadata.")
    ap.add_argument("-L", type=int, default=0, help="Samples per waveform override. Default: read scan metadata.")
    ap.add_argument("--fs", type=float, default=0.0, help="Sampling rate override (Hz). Default 62.5e6.")
    ap.add_argument("--max_waves", type=int, default=0, help="Max waveforms loaded per point/channel (0 = all)")
    ap.add_argument("--fft_avg_waves", type=int, default=2000, help="Waveforms averaged in FFT per point")
    ap.add_argument("--fft_window", default="", help="FFT window override")
    ap.add_argument("--fft_log_x", action="store_true", help="Use log-x FFT overlays")
    ap.add_argument("--fft_keep_dc", action="store_true", help="Keep DC in FFT metrics/plots")
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed")
    ap.add_argument("--prefix", default="fft_metrics_", help="Per-point output prefix")
    ap.add_argument("--analysis-dir", default="", help="Run-level output directory (default: <run_dir>/analysis_fft_metrics)")
    ap.add_argument("--focus-channel", type=int, default=21, help="Also export a per-vgain summary for this channel")
    ap.add_argument("--force", action="store_true", help="Re-run per-point analysis even if outputs already exist")
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


def parse_scan_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def point_sort_key(path: Path) -> tuple[int, str]:
    try:
        return (int(path.name.split("_")[-1]), path.name)
    except ValueError:
        return (sys.maxsize, path.name)


def discover_points(run_dir: Path) -> list[Path]:
    candidates = [p for p in run_dir.glob("vgain_*") if p.is_dir()]
    if candidates:
        return sorted(candidates, key=point_sort_key)
    points_dir = run_dir / "points"
    return sorted([p for p in points_dir.glob("vgain_*") if p.is_dir()], key=point_sort_key)


def load_config(run_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    meta = parse_scan_metadata(run_dir / "scan_metadata.txt")
    manifest = parse_scan_manifest(run_dir / "scan_manifest.json")

    channels = args.channels
    if not channels:
        if "channels" in meta:
            channels = meta["channels"]
        elif isinstance(manifest.get("channels"), list):
            channels = ",".join(str(ch) for ch in manifest["channels"])

    n_samples = args.L
    if n_samples <= 0:
        if "waveform_len" in meta:
            n_samples = int(meta["waveform_len"])
        else:
            n_samples = int(manifest.get("waveform_len", 0))

    fs_hz = args.fs
    if fs_hz <= 0:
        fs_hz = float(manifest.get("sampling_rate_hz", 62.5e6))

    return {
        "channels": channels,
        "n_samples": n_samples,
        "fs_hz": fs_hz,
    }


def build_cmd(point_dir: Path, args: argparse.Namespace, cfg: dict[str, Any]) -> list[str]:
    cmd = [
        sys.executable,
        str(ANALYZER),
        "--folder",
        str(point_dir),
        "--channels",
        str(cfg["channels"]),
        "-L",
        str(cfg["n_samples"]),
        "--fs",
        str(cfg["fs_hz"]),
        "--max_waves",
        str(args.max_waves),
        "--fft_avg_waves",
        str(args.fft_avg_waves),
        "--interpret",
        args.interpret,
        "--prefix",
        args.prefix,
        "--title",
        point_dir.parent.name,
        "--subtitle",
        point_dir.name,
        "--no-show",
    ]
    if args.fft_window:
        cmd.extend(["--fft_window", args.fft_window])
    if args.fft_log_x:
        cmd.append("--fft_log_x")
    if args.fft_keep_dc:
        cmd.append("--fft_keep_dc")
    return cmd


def run_point_analysis(point_dir: Path, args: argparse.Namespace, cfg: dict[str, Any]) -> None:
    out_csv = point_dir / f"{args.prefix}noise_metrics.csv"
    log_path = point_dir / f"{args.prefix}analysis.log"
    if out_csv.exists() and not args.force:
        return

    cmd = build_cmd(point_dir, args, cfg)
    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write("Command:\n")
        handle.write(" ".join(cmd) + "\n\n")
        handle.flush()
        subprocess.run(cmd, cwd=ROOT_DIR, env=env, stdout=handle, stderr=subprocess.STDOUT, check=True)


def load_point_rows(point_dir: Path, prefix: str, vgain: int) -> list[dict[str, Any]]:
    csv_path = point_dir / f"{prefix}noise_metrics.csv"
    rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            item = dict(row)
            item["vgain"] = vgain
            item["point_dir"] = point_dir.name
            rows.append(item)
    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def write_json(payload: Any, path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 2
    if not ANALYZER.exists():
        print(f"Analyzer not found: {ANALYZER}", file=sys.stderr)
        return 2

    points = discover_points(run_dir)
    if not points:
        print(f"No vgain point directories found in {run_dir}", file=sys.stderr)
        return 2

    cfg = load_config(run_dir, args)
    if not cfg["channels"]:
        print("Channels could not be inferred. Provide --channels.", file=sys.stderr)
        return 2
    if int(cfg["n_samples"]) <= 0:
        print("Waveform length could not be inferred. Provide -L.", file=sys.stderr)
        return 2

    analysis_dir = Path(args.analysis_dir).expanduser().resolve() if args.analysis_dir else (run_dir / "analysis_fft_metrics")
    analysis_dir.mkdir(parents=True, exist_ok=True)

    merged_rows: list[dict[str, Any]] = []
    processed_points: list[dict[str, Any]] = []

    for point_dir in points:
        vgain = int(point_sort_key(point_dir)[0])
        print(f"[analyze] {point_dir.name}")
        run_point_analysis(point_dir, args, cfg)
        rows = load_point_rows(point_dir, args.prefix, vgain)
        merged_rows.extend(rows)
        processed_points.append(
            {
                "vgain": vgain,
                "point_dir": point_dir.name,
                "metrics_csv": str(point_dir / f"{args.prefix}noise_metrics.csv"),
                "metrics_json": str(point_dir / f"{args.prefix}noise_metrics.json"),
                "fft_overlay_png": str(point_dir / f"{args.prefix}fft_overlay.png"),
                "analysis_log": str(point_dir / f"{args.prefix}analysis.log"),
            }
        )

    merged_rows.sort(key=lambda row: (int(row["vgain"]), int(row["channel"])))
    write_csv(merged_rows, analysis_dir / "all_points_noise_metrics.csv")
    write_json(merged_rows, analysis_dir / "all_points_noise_metrics.json")

    if args.focus_channel >= 0:
        focus_rows = [row for row in merged_rows if int(row["channel"]) == int(args.focus_channel)]
        if focus_rows:
            focus_rows.sort(key=lambda row: int(row["vgain"]))
            write_csv(focus_rows, analysis_dir / f"channel_{args.focus_channel:02d}_vs_vgain.csv")
            write_json(focus_rows, analysis_dir / f"channel_{args.focus_channel:02d}_vs_vgain.json")

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "type": "dark_vgain_scan_fft_metrics",
        "run_dir": str(run_dir),
        "point_count": len(points),
        "channels": cfg["channels"],
        "waveform_len": int(cfg["n_samples"]),
        "fs_hz": float(cfg["fs_hz"]),
        "max_waves": int(args.max_waves),
        "fft_avg_waves": int(args.fft_avg_waves),
        "fft_window": args.fft_window,
        "fft_log_x": bool(args.fft_log_x),
        "fft_keep_dc": bool(args.fft_keep_dc),
        "interpret": args.interpret,
        "prefix": args.prefix,
        "focus_channel": int(args.focus_channel),
        "processed_points": processed_points,
    }
    write_json(manifest, analysis_dir / "analysis_manifest.json")

    print("\nSaved:")
    print(f"  {analysis_dir / 'all_points_noise_metrics.csv'}")
    print(f"  {analysis_dir / 'all_points_noise_metrics.json'}")
    if args.focus_channel >= 0:
        print(f"  {analysis_dir / f'channel_{args.focus_channel:02d}_vs_vgain.csv'}")
        print(f"  {analysis_dir / f'channel_{args.focus_channel:02d}_vs_vgain.json'}")
    print(f"  {analysis_dir / 'analysis_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
