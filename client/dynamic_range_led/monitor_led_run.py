#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Monitor a dynamic_range_led run directory.")
    ap.add_argument("run_dir", help="Run directory containing scan_manifest.json and points/")
    ap.add_argument("--interval", type=float, default=5.0, help="Refresh interval in seconds")
    ap.add_argument("--once", action="store_true", help="Print one snapshot and exit")
    ap.add_argument("--json", action="store_true", help="Print compact JSON instead of a text table")
    return ap.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def planned_points(manifest: dict[str, Any]) -> int | None:
    for key in ("intensity_values", "vgain_values", "offset_values", "points"):
        value = manifest.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def point_sort_key(path: Path) -> tuple[int, str]:
    name = path.name
    try:
        suffix = name.split("_")[-1]
        return (int(suffix), name)
    except ValueError:
        return (sys.maxsize, name)


def collect(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "scan_manifest.json"
    points_dir = run_dir / "points"

    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    point_dirs = sorted(
        [p for p in points_dir.glob("*") if p.is_dir()],
        key=point_sort_key,
    )

    counts: Counter[str] = Counter()
    latest_point = "-"
    latest_status = "-"
    newest_mtime = 0.0
    newest_file = "-"

    for point_dir in point_dirs:
        metadata_path = point_dir / "metadata.json"
        latest_point = point_dir.name
        if metadata_path.exists():
            data = load_json(metadata_path)
            status = str(data.get("status", "unknown"))
            counts[status] += 1
            latest_status = status
            mtime = metadata_path.stat().st_mtime
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest_file = point_dir.name
        else:
            counts["no_metadata"] += 1
            latest_status = "no_metadata"

    total_seen = sum(counts.values())
    planned = planned_points(manifest)
    active = sorted([status for status in counts if status in {"started", "captured"}])

    return {
        "run_dir": str(run_dir),
        "planned_points": planned,
        "seen_points": total_seen,
        "done_points": counts.get("analyzed", 0),
        "active_points": sum(counts.get(s, 0) for s in ("started", "captured")),
        "failed_points": sum(
            count for status, count in counts.items() if status not in {"analyzed", "started", "captured"}
        ),
        "status_counts": dict(sorted(counts.items())),
        "latest_point": latest_point,
        "latest_status": latest_status,
        "most_recent_metadata_point": newest_file,
        "created_utc": manifest.get("created_utc"),
        "scan_type": manifest.get("scan_wavelength") or manifest.get("type") or "unknown",
        "active_statuses": active,
    }


def render_text(snapshot: dict[str, Any]) -> str:
    planned = snapshot["planned_points"]
    seen = snapshot["seen_points"]
    done = snapshot["done_points"]
    active = snapshot["active_points"]
    failed = snapshot["failed_points"]
    percent = ""
    if planned:
        percent = f" ({100.0 * done / planned:5.1f}%)"

    lines = [
        f"run_dir: {snapshot['run_dir']}",
        f"planned: {planned if planned is not None else '-'}",
        f"seen:    {seen}",
        f"done:    {done}{percent}",
        f"active:  {active}",
        f"failed:  {failed}",
        f"latest:  {snapshot['latest_point']} [{snapshot['latest_status']}]",
        f"recent:  {snapshot['most_recent_metadata_point']}",
        "statuses:",
    ]
    counts = snapshot["status_counts"]
    if counts:
        for status, count in counts.items():
            lines.append(f"  {status:>12}: {count}")
    else:
        lines.append("  (no points yet)")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists():
        print(f"run directory not found: {run_dir}", file=sys.stderr)
        return 2

    while True:
        snapshot = collect(run_dir)
        if args.json:
            print(json.dumps(snapshot, sort_keys=True))
        else:
            if not args.once:
                os.system("clear")
            print(render_text(snapshot))

        if args.once:
            return 0
        time.sleep(max(args.interval, 0.2))


if __name__ == "__main__":
    raise SystemExit(main())
