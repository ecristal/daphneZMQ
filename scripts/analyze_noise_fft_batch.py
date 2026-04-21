#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
GENERIC_ANALYZER = ROOT_DIR / "client" / "analyze_waveform_dataset.py"
DARK_ANALYZER = ROOT_DIR / "scripts" / "analyze_dark_vgain_scan.py"

DEFAULT_ROOTS = [
    ROOT_DIR / "client" / "dynamic_range_led" / "runs",
    ROOT_DIR / "client" / "dark_vgain_runs",
    ROOT_DIR / "client" / "osc_runs",
]

SKIP_PARTS = {
    ".build",
    "__pycache__",
    "analysis_fft_metrics",
    "cpp_snr_scan_p30",
}

SKIP_SUBSTRINGS = (
    "failed",
    "dryrun",
)


@dataclass(frozen=True)
class GenericTarget:
    folder: Path
    channels: str
    n_samples: int
    title: str
    subtitle: str


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Batch FFT/noise-metrics analysis across dark scans, LED waveform folders, and osc captures."
    )
    ap.add_argument(
        "roots",
        nargs="*",
        default=[str(path) for path in DEFAULT_ROOTS],
        help="Root directories to scan. Defaults to dynamic_range_led/runs, dark_vgain_runs, and osc_runs.",
    )
    ap.add_argument("--max_waves", type=int, default=0, help="Max waveforms loaded per channel (0 = all)")
    ap.add_argument("--fft_avg_waves", type=int, default=2000, help="Waveforms averaged in FFT")
    ap.add_argument("--prefix", default="fft_metrics_", help="Output prefix for per-folder files")
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed")
    ap.add_argument("--fft_log_x", action="store_true", help="Use log-x FFT overlays")
    ap.add_argument("--fft_keep_dc", action="store_true", help="Keep DC in FFT metrics/plots")
    ap.add_argument("--fs", type=float, default=62.5e6, help="Sampling rate used when metadata does not provide one")
    ap.add_argument("--force", action="store_true", help="Re-run analyses even if outputs already exist")
    ap.add_argument("--dry-run", action="store_true", help="Only print what would be analyzed")
    return ap.parse_args()


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if SKIP_PARTS & parts:
        return True
    path_str = str(path).lower()
    return any(token in path_str for token in SKIP_SUBSTRINGS)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def discover_channels_from_files(folder: Path) -> list[int]:
    out: list[int] = []
    for item in folder.glob("channel_*.dat"):
        try:
            out.append(int(item.stem.split("_", 1)[1]))
        except Exception:
            continue
    return sorted(set(out))


def parse_channels_value(value: Any) -> list[int]:
    if isinstance(value, list):
        out: list[int] = []
        for item in value:
            try:
                out.append(int(item))
            except Exception:
                continue
        return sorted(set(out))
    if isinstance(value, str):
        out: list[int] = []
        for token in value.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                out.append(int(token))
            except Exception:
                continue
        return sorted(set(out))
    return []


def infer_from_command_tokens(tokens: list[Any]) -> tuple[list[int], int]:
    channels: list[int] = []
    n_samples = 0
    clean = [str(tok) for tok in tokens]
    for idx, tok in enumerate(clean):
        if tok == "-channel_list" and idx + 1 < len(clean):
            channels = parse_channels_value(clean[idx + 1])
        elif tok == "-L" and idx + 1 < len(clean):
            try:
                n_samples = int(clean[idx + 1])
            except Exception:
                pass
    return channels, n_samples


def infer_generic_target(folder: Path) -> GenericTarget | None:
    run_meta = load_json(folder / "run_metadata.json")
    local_meta = load_json(folder / "metadata.json")
    parent_meta = load_json(folder.parent / "metadata.json")

    channels = parse_channels_value(run_meta.get("channels"))
    if not channels:
        channels = parse_channels_value(local_meta.get("channels"))
    if not channels:
        channels = parse_channels_value(parent_meta.get("channels"))
    if not channels:
        cmd_channels, _ = infer_from_command_tokens(parent_meta.get("acquire_command", []))
        channels = cmd_channels
    if not channels:
        channels = discover_channels_from_files(folder)
    if not channels:
        return None

    n_samples = int(run_meta.get("samples_per_waveform", 0) or 0)
    if n_samples <= 0:
        n_samples = int(local_meta.get("waveform_len", 0) or 0)
    if n_samples <= 0:
        n_samples = int(parent_meta.get("waveform_len", 0) or 0)
    if n_samples <= 0:
        _, cmd_n_samples = infer_from_command_tokens(parent_meta.get("acquire_command", []))
        n_samples = cmd_n_samples
    if n_samples <= 0:
        return None

    if folder.name == "raw":
        title = folder.parents[1].name if len(folder.parents) > 1 else folder.parent.name
        subtitle = folder.parent.name
    else:
        title = folder.parent.name
        subtitle = folder.name

    return GenericTarget(
        folder=folder,
        channels=",".join(str(ch) for ch in channels),
        n_samples=n_samples,
        title=title,
        subtitle=subtitle,
    )


def discover_dark_runs(roots: list[Path]) -> list[Path]:
    runs: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.iterdir():
            if not candidate.is_dir() or should_skip(candidate):
                continue
            if any(point.is_dir() for point in candidate.glob("vgain_*")):
                runs.add(candidate.resolve())
    return sorted(runs)


def is_under_any(path: Path, parents: list[Path]) -> bool:
    for parent in parents:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            continue
    return False


def discover_generic_targets(roots: list[Path], dark_runs: list[Path]) -> list[GenericTarget]:
    targets: list[GenericTarget] = []
    seen: set[Path] = set()
    resolved_dark = [path.resolve() for path in dark_runs]

    for root in roots:
        if not root.exists():
            continue
        for folder in root.rglob("*"):
            if not folder.is_dir() or should_skip(folder):
                continue
            resolved = folder.resolve()
            if resolved in seen or is_under_any(resolved, resolved_dark):
                continue
            if not any(folder.glob("channel_*.dat")):
                continue
            target = infer_generic_target(folder)
            if target is None:
                continue
            targets.append(target)
            seen.add(resolved)
    return sorted(targets, key=lambda item: str(item.folder))


def generic_output_exists(target: GenericTarget, prefix: str) -> bool:
    return (target.folder / f"{prefix}noise_metrics.csv").exists()


def run_dark_analysis(run_dir: Path, args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        str(DARK_ANALYZER),
        str(run_dir),
        "--max_waves",
        str(args.max_waves),
        "--fft_avg_waves",
        str(args.fft_avg_waves),
        "--prefix",
        args.prefix,
        "--interpret",
        args.interpret,
    ]
    if args.fft_log_x:
        cmd.append("--fft_log_x")
    if args.fft_keep_dc:
        cmd.append("--fft_keep_dc")
    if args.force:
        cmd.append("--force")

    print(f"[dark] {run_dir}")
    if args.dry_run:
        print("  " + " ".join(cmd))
        return

    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    subprocess.run(cmd, cwd=ROOT_DIR, env=env, check=True)


def run_generic_analysis(target: GenericTarget, args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        str(GENERIC_ANALYZER),
        "--folder",
        str(target.folder),
        "--channels",
        target.channels,
        "-L",
        str(target.n_samples),
        "--fs",
        str(args.fs),
        "--max_waves",
        str(args.max_waves),
        "--fft_avg_waves",
        str(args.fft_avg_waves),
        "--interpret",
        args.interpret,
        "--prefix",
        args.prefix,
        "--title",
        target.title,
        "--subtitle",
        target.subtitle,
        "--no-show",
    ]
    if args.fft_log_x:
        cmd.append("--fft_log_x")
    if args.fft_keep_dc:
        cmd.append("--fft_keep_dc")

    print(f"[generic] {target.folder}")
    if args.dry_run:
        print("  " + " ".join(cmd))
        return

    env = os.environ.copy()
    env.setdefault("MPLBACKEND", "Agg")
    subprocess.run(cmd, cwd=ROOT_DIR, env=env, check=True)


def main() -> int:
    args = parse_args()
    roots = [Path(path).expanduser().resolve() for path in args.roots]

    for root in roots:
        if not root.exists():
            print(f"[skip-root] missing {root}")

    dark_runs = discover_dark_runs(roots)
    generic_targets = discover_generic_targets(roots, dark_runs)

    dark_to_run = []
    for run_dir in dark_runs:
        run_level_csv = run_dir / "analysis_fft_metrics" / "all_points_noise_metrics.csv"
        if run_level_csv.exists() and not args.force:
            continue
        dark_to_run.append(run_dir)

    generic_to_run = []
    for target in generic_targets:
        if generic_output_exists(target, args.prefix) and not args.force:
            continue
        generic_to_run.append(target)

    print(f"Roots: {len([root for root in roots if root.exists()])}")
    print(f"Dark runs discovered: {len(dark_runs)}")
    print(f"Dark runs to analyze: {len(dark_to_run)}")
    print(f"Generic waveform folders discovered: {len(generic_targets)}")
    print(f"Generic waveform folders to analyze: {len(generic_to_run)}")

    for run_dir in dark_to_run:
        run_dark_analysis(run_dir, args)
    for target in generic_to_run:
        run_generic_analysis(target, args)

    print("Batch FFT/noise analysis completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
