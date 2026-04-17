#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scan_led_intensity_charge import choose_best_by_channel


SUMMARY_FIELDS = [
    "channel",
    "intensity",
    "scan_wavelength",
    "signal_fraction",
    "balance_error",
    "snr_estimate",
    "threshold_charge",
    "integrate_start",
    "integrate_stop",
    "peak_index",
    "onset_index",
    "output_dir",
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Merge multiple LED intensity scan runs into a single logical run directory."
    )
    ap.add_argument("output_dir", help="Merged run directory to create")
    ap.add_argument("run_dirs", nargs="+", help="Source run directories, in preference order")
    return ap.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_complete_point(point_dir: Path) -> bool:
    return (point_dir / "metadata.json").exists() and (point_dir / "analysis.json").exists()


def ensure_same_config(manifests: list[dict[str, Any]]) -> None:
    keys = [
        "channels",
        "scan_wavelength",
        "waveforms",
        "waveform_len",
        "led_channel_mask",
        "pulse_width_ticks",
        "host",
        "port",
        "route",
    ]
    base = manifests[0]
    for idx, manifest in enumerate(manifests[1:], start=2):
        mismatches = [key for key in keys if manifest.get(key) != base.get(key)]
        if mismatches:
            raise ValueError(f"Run #{idx} has incompatible manifest fields: {', '.join(mismatches)}")


def build_point_rows(merged_points_dir: Path, channels: list[int], scan_wavelength: str) -> list[dict[str, Any]]:
    point_rows: list[dict[str, Any]] = []
    for point_dir in sorted(merged_points_dir.glob("intensity_*")):
        if not is_complete_point(point_dir):
            continue
        intensity = int(point_dir.name.split("_", 1)[1])
        analysis = load_json(point_dir / "analysis.json")["analysis"]
        for ch in channels:
            ch_data = analysis[str(ch)]
            metrics = ch_data["metrics"]
            point_rows.append(
                {
                    "channel": ch,
                    "intensity": intensity,
                    "scan_wavelength": scan_wavelength,
                    "signal_fraction": metrics.get("signal_fraction"),
                    "balance_error": metrics.get("balance_error"),
                    "snr_estimate": metrics.get("snr_estimate"),
                    "threshold_charge": metrics.get("threshold_charge"),
                    "integrate_start": ch_data["integrate_start"],
                    "integrate_stop": ch_data["integrate_stop"],
                    "peak_index": ch_data["peak_index"],
                    "onset_index": ch_data["onset_index"],
                    "output_dir": str(point_dir),
                }
            )
    return point_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    run_dirs = [Path(p).expanduser().resolve() for p in args.run_dirs]
    manifests = [load_json(run_dir / "scan_manifest.json") for run_dir in run_dirs]
    ensure_same_config(manifests)

    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")

    output_dir.mkdir(parents=True)
    points_dir = output_dir / "points"
    points_dir.mkdir()

    base_manifest = dict(manifests[0])
    selected_points: dict[int, Path] = {}
    selected_sources: dict[int, str] = {}
    source_summaries: list[dict[str, Any]] = []

    for run_dir in run_dirs:
        complete = []
        points_path = run_dir / "points"
        for point_dir in sorted(points_path.glob("intensity_*")):
            point_name = point_dir.name
            intensity = int(point_name.split("_", 1)[1])
            if is_complete_point(point_dir):
                selected_points[intensity] = point_dir
                selected_sources[intensity] = str(run_dir)
                complete.append(intensity)
        source_summaries.append({"run_dir": str(run_dir), "complete_intensities": complete})

    for intensity, source_point in sorted(selected_points.items()):
        link_path = points_dir / f"intensity_{intensity:04d}"
        os.symlink(source_point, link_path)

    merged_intensities = sorted(selected_points)
    base_manifest["intensity_values"] = merged_intensities
    base_manifest["created_utc"] = utc_now()
    base_manifest["merged_from_runs"] = [str(run_dir) for run_dir in run_dirs]
    base_manifest["merged_complete_intensities"] = merged_intensities
    (output_dir / "scan_manifest.json").write_text(
        json.dumps(base_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    merge_info = {
        "created_utc": utc_now(),
        "output_dir": str(output_dir),
        "sources": source_summaries,
        "selected_sources": {str(k): v for k, v in sorted(selected_sources.items())},
    }
    (output_dir / "merge_info.json").write_text(
        json.dumps(merge_info, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for name in ("fe_state_readback.json", "fe_state_readback.log"):
        src = run_dirs[0] / name
        if src.exists():
            os.symlink(src, output_dir / name)
    stop_src = next((run_dir / "led_stop.log" for run_dir in reversed(run_dirs) if (run_dir / "led_stop.log").exists()), None)
    if stop_src:
        os.symlink(stop_src, output_dir / "led_stop.log")

    point_rows = build_point_rows(points_dir, list(base_manifest["channels"]), str(base_manifest["scan_wavelength"]))
    if point_rows:
        write_csv(output_dir / "summary_by_point.csv", point_rows)
        best_rows = choose_best_by_channel(point_rows)
        write_csv(output_dir / "best_by_channel.csv", best_rows)

    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
