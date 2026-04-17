#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from client.analyze_waveform_dataset import (  # noqa: E402
    compute_avg_fft_dbfs,
    compute_noise_metrics,
    discover_channels,
    get_window,
    load_channel_waves,
)


DARK_ROOT = ROOT_DIR / "client" / "dark_vgain_runs"
OSC_ROOT = ROOT_DIR / "client" / "osc_runs"
LED_ROOT = ROOT_DIR / "client" / "dynamic_range_led" / "runs"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "client" / "no_bias_noise_study_20260325"
DEFAULT_LXPLUS_INDEX = DEFAULT_OUTPUT_DIR / "lxplus_2026March_topdirs.txt"
LXPLUS_BASE = "/eos/experiment/neutplatform/protodune/experiments/ColdBoxVD/2026March"

MANUAL_RUN_OVERRIDES: dict[str, dict[str, Any]] = {
    "20260319_daphne-13_dark_vgain_scan": {
        "technology_layout": "AFE0:VD",
        "notes_append": "manual override: VD board connected to AFE0",
    },
    "20260319_daphne13_osc_capture": {
        "technology_layout": "AFE0:VD",
        "notes_append": "manual override: VD board connected to AFE0",
    },
    "20260316_090150_daphne-13_dark_vgain_scan": {
        "include_in_noise_analysis": False,
        "analysis_status": "excluded_manual",
        "notes_append": "manual override: excluded from comparison",
    },
}


@dataclass
class RunRecord:
    run_name: str
    run_kind: str
    stimulus: str
    no_bias_status: str
    include_in_noise_analysis: bool
    source_root: str
    local_path: str
    lxplus_path: str
    present_local: bool
    present_on_lxplus: bool
    channels: str
    waveform_len: int
    waveforms_per_point: int
    biasctrl_dac: str
    afe_bias_overrides: str
    notes: str
    run_label: str
    config_summary: str
    connection_mode: str
    topology_label: str
    technology_layout: str
    selected_dataset_path: str
    selected_setting_kind: str
    selected_setting_value: str
    analysis_status: str


@dataclass
class AnalysisResult:
    run_name: str
    run_kind: str
    connection_mode: str
    topology_label: str
    technology_layout: str
    selected_dataset_path: str
    selected_setting_kind: str
    selected_setting_value: str
    channels: list[int]
    mean_abs_corr_all: float
    mean_abs_corr_within_afe: float
    mean_abs_corr_cross_afe: float
    mean_abs_corr_with_afe3: float
    max_abs_corr_pair: str
    max_abs_corr_value: float
    median_fft_floor_dbfs: float
    median_fft_peak_dbfs: float
    median_fft_peak_minus_floor_db: float
    median_ac_rms_counts: float
    top_outlier_channels: str


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build a no-bias run database and run FFT/cross-correlation checks across local DAPHNE datasets."
    )
    ap.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for database CSV/JSON and analysis products.",
    )
    ap.add_argument(
        "--lxplus-index",
        default=str(DEFAULT_LXPLUS_INDEX),
        help="Optional text file with one lxplus top-level run path per line.",
    )
    ap.add_argument("--target-vgain", type=int, default=1000, help="Representative vgain for dark scans.")
    ap.add_argument("--max-waves", type=int, default=512, help="Waveforms loaded per channel for comparison.")
    ap.add_argument("--fft-avg-waves", type=int, default=512, help="Waveforms averaged in FFT per channel.")
    ap.add_argument(
        "--fft-window",
        default="BLACKMAN-HARRIS",
        help="FFT window passed to the shared analyzer helpers.",
    )
    ap.add_argument("--fs", type=float, default=62.5e6, help="Default sampling rate in Hz.")
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed")
    ap.add_argument(
        "--include-led-stimulus",
        action="store_true",
        help="Also run cross-correlation analysis on no-bias LED scans. By default they stay in the database only.",
    )
    ap.add_argument("--force", action="store_true", help="Recompute outputs even if they already exist.")
    return ap.parse_args()


def parse_kv_text(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def parse_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def split_csv_ints(value: str) -> list[int]:
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


def parse_group_specs(value: str) -> list[int]:
    out: list[int] = []
    if not value:
        return out
    for group in value.split(";"):
        if ":" not in group:
            continue
        channels_part, _setting = group.split(":", 1)
        out.extend(split_csv_ints(channels_part))
    return sorted(set(out))


def classify_dark_connection(name: str) -> tuple[str, str]:
    lname = name.lower()
    if "open_channel" in lname:
        return "open_reference", "Open channels, no mezzanine reference"
    if "detector_connected_up" in lname:
        return "detector_connected_up", "Detector connected, cable up"
    if "detector_connected_down" in lname:
        return "detector_connected_down", "Detector connected, cable down"
    if "detector_connected" in lname:
        return "detector_connected", "Detector connected"
    if "afe" in lname and "connected" in lname:
        return "single_afe_connection", "Single AFE mezzanine connected"
    if "no_choke" in lname:
        return "open_reference_variant", "Open-channel reference variant without choke"
    if "vdmezz" in lname:
        return "mezzanine_only", "Mezzanine-only study"
    return "reference_or_unknown", "Reference or unknown dark run"


def classify_osc_connection(name: str, notes: str) -> tuple[str, str]:
    lname = name.lower()
    lnotes = notes.lower()
    if "not_connected" in lname:
        return "open_reference", "Detector not connected"
    if "ledoff" in lname:
        return "no_led_capture", "LED disabled osc capture"
    if "bias_off" in lname and "connected" in lname:
        return "detector_connected_bias_off", "Detector connected, bias off"
    if "bias_on" in lname:
        return "detector_connected_bias_on", "Detector connected, bias on"
    if "led" in lname:
        return "stimulated_capture", "LED stimulation capture"
    if "osc_capture" in lname:
        return "capture_unknown_bias", "Oscilloscope capture with bias not explicit"
    if "bias off" in lnotes:
        return "detector_connected_bias_off", "Detector connected, bias off"
    return "osc_unknown", "Oscilloscope capture"


def infer_technology_layout(name: str, channels: list[int], notes: str = "") -> str:
    lname = name.lower()
    if "vd02_hd13" in lname:
        return "AFE0:VD,AFE1:HD,AFE2:VD,AFE3:HD"
    if "vd0_hd13_sof_2" in lname:
        return "AFE0:VD,AFE1:HD,AFE2:SoF,AFE3:HD"
    if "sof" in lname and channels and min(channels) >= 16:
        return "AFE2:SoF"
    if "hd" in lname and channels and min(channels) >= 8 and max(channels) <= 15:
        return "AFE1:HD"
    if "vd" in lname and channels and max(channels) <= 7:
        return "AFE0:VD"
    if "vdmezz" in lname:
        return "Mezzanine-study"
    if "open_channel" in lname:
        return "Open-reference"
    if "daphne" in lname and not notes:
        return "Unknown"
    return "Unknown"


def dark_selected_point(run_dir: Path, target_vgain: int) -> tuple[Path | None, str, str]:
    points = sorted([p for p in run_dir.glob("vgain_*") if p.is_dir()])
    if not points:
        points = sorted([p for p in (run_dir / "points").glob("vgain_*") if p.is_dir()]) if (run_dir / "points").exists() else []
    if not points:
        return None, "", ""
    scored: list[tuple[int, Path]] = []
    for point in points:
        try:
            vgain = int(point.name.split("_")[-1])
        except Exception:
            continue
        scored.append((vgain, point))
    if not scored:
        return None, "", ""
    exact = [item for item in scored if item[0] == target_vgain]
    if exact:
        return exact[0][1], "vgain", str(exact[0][0])
    best = min(scored, key=lambda item: (abs(item[0] - target_vgain), item[0]))
    return best[1], "vgain", str(best[0])


def is_no_bias_dark(meta: dict[str, str]) -> bool:
    if meta.get("biasctrl_dac", "") not in {"0", "0.0", ""}:
        return False
    afe = meta.get("afe_bias_overrides", "")
    if not afe:
        return True
    return all(part.split(":")[-1].strip() in {"0", "0.0"} for part in afe.split(",") if ":" in part)


def is_no_bias_led_scan(meta: dict[str, str], name: str) -> bool:
    if "nobias" in name.lower() or "no_bias" in name.lower():
        return True
    return meta.get("biasctrl_dac", "") in {"0", "0.0"}


def is_no_bias_osc(name: str, notes: str) -> str:
    lname = name.lower()
    lnotes = notes.lower()
    if "pofon" in lname or "pof on" in lname or "pof on" in lnotes or "power over fiber on" in lnotes:
        return "no"
    if "0 bias" in lnotes or "0bias" in lname:
        return "yes"
    if "bias_off" in lname or "bias off" in lnotes:
        return "yes"
    if "connected and open" in lnotes and "ledoff" in lname and "bias" not in lnotes:
        return "yes"
    if "bias_on" in lname or "bias on" in lnotes:
        return "no"
    if "biased" in lnotes:
        return "no"
    return "unknown"


def load_lxplus_index(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or not line.startswith("/"):
            continue
        name = Path(line).name
        if name in {"dark_vgain_runs", "dynamic_range_led", "osc_runs"}:
            continue
        out[name] = line
    return out


def append_osc_record(
    records: list[RunRecord],
    run_dir: Path,
    source_root: str,
    lxplus_path: str = "",
    present_on_lxplus: bool = False,
) -> None:
    meta = parse_json(run_dir / "run_metadata.json")
    if not meta:
        return
    notes = str(meta.get("run_notes", ""))
    no_bias = is_no_bias_osc(run_dir.name, notes)
    if no_bias == "no":
        return
    channels = [int(ch) for ch in meta.get("channels", []) if isinstance(ch, int)]
    mode, label = classify_osc_connection(run_dir.name, notes)
    records.append(
        RunRecord(
            run_name=run_dir.name,
            run_kind="osc",
            stimulus="osc",
            no_bias_status=no_bias,
            include_in_noise_analysis=no_bias == "yes",
            source_root=source_root,
            local_path=str(run_dir),
            lxplus_path=lxplus_path,
            present_local=True,
            present_on_lxplus=present_on_lxplus,
            channels=",".join(str(ch) for ch in channels),
            waveform_len=int(meta.get("samples_per_waveform", 0) or 0),
            waveforms_per_point=0,
            biasctrl_dac="0" if no_bias == "yes" else "",
            afe_bias_overrides="",
            notes=notes,
            run_label=str(meta.get("run_label", "")),
            config_summary=f"osc capture, sw_trigger={bool(meta.get('software_trigger', False))}, route={meta.get('route','')}",
            connection_mode=mode,
            topology_label=label,
            technology_layout=infer_technology_layout(run_dir.name, channels, notes),
            selected_dataset_path=str(run_dir),
            selected_setting_kind="fixed",
            selected_setting_value="",
            analysis_status="pending" if no_bias == "yes" else "excluded_unknown_bias",
        )
    )


def build_local_records(target_vgain: int, include_led_stimulus: bool, import_root: Path) -> list[RunRecord]:
    records: list[RunRecord] = []

    for run_dir in sorted(DARK_ROOT.iterdir()):
        meta = parse_kv_text(run_dir / "scan_metadata.txt")
        if not meta:
            continue
        channels = split_csv_ints(meta.get("channels", ""))
        if not is_no_bias_dark(meta):
            continue
        mode, label = classify_dark_connection(run_dir.name)
        selected_path, selected_kind, selected_value = dark_selected_point(run_dir, target_vgain)
        records.append(
            RunRecord(
                run_name=run_dir.name,
                run_kind="dark_vgain",
                stimulus="dark",
                no_bias_status="yes",
                include_in_noise_analysis=selected_path is not None,
                source_root="dark_vgain_runs",
                local_path=str(run_dir),
                lxplus_path="",
                present_local=True,
                present_on_lxplus=False,
                channels=",".join(str(ch) for ch in channels),
                waveform_len=int(meta.get("waveform_len", "0") or 0),
                waveforms_per_point=int(meta.get("waveforms_per_point", "0") or 0),
                biasctrl_dac=meta.get("biasctrl_dac", ""),
                afe_bias_overrides=meta.get("afe_bias_overrides", ""),
                notes="",
                run_label=run_dir.name,
                config_summary=f"dark scan, offset={meta.get('ch_offset','')}, route={meta.get('route','')}",
                connection_mode=mode,
                topology_label=label,
                technology_layout=infer_technology_layout(run_dir.name, channels),
                selected_dataset_path=str(selected_path) if selected_path else "",
                selected_setting_kind=selected_kind,
                selected_setting_value=selected_value,
                analysis_status="pending" if selected_path else "missing_point",
            )
        )

    for run_dir in sorted(OSC_ROOT.iterdir()):
        append_osc_record(records, run_dir, "osc_runs")

    if import_root.exists():
        for meta_path in sorted(import_root.rglob("run_metadata.json")):
            run_dir = meta_path.parent
            rel = run_dir.relative_to(import_root)
            lx_path = f"{LXPLUS_BASE}/20260323_softwaretriggerchecks_noLED/{rel.as_posix()}"
            append_osc_record(records, run_dir, "lxplus_imports", lxplus_path=lx_path, present_on_lxplus=True)

    for run_dir in sorted(LED_ROOT.iterdir()):
        meta = parse_kv_text(run_dir / "scan_metadata.txt")
        if not meta:
            meta = parse_kv_text(run_dir / "run_metadata.txt")
        if not meta:
            continue
        if not is_no_bias_led_scan(meta, run_dir.name):
            continue
        channels = parse_group_specs(meta.get("group_specs", ""))
        if not channels:
            channels = split_csv_ints(meta.get("channels", ""))
        include = include_led_stimulus
        records.append(
            RunRecord(
                run_name=run_dir.name,
                run_kind="led_vgain",
                stimulus="led",
                no_bias_status="yes",
                include_in_noise_analysis=include,
                source_root="dynamic_range_led",
                local_path=str(run_dir),
                lxplus_path="",
                present_local=True,
                present_on_lxplus=False,
                channels=",".join(str(ch) for ch in channels),
                waveform_len=int(meta.get("waveform_len", "0") or 0),
                waveforms_per_point=int(meta.get("waveforms_per_point", "0") or 0),
                biasctrl_dac=meta.get("biasctrl_dac", ""),
                afe_bias_overrides=meta.get("fixed_afe_bias_overrides", ""),
                notes=f"group_specs={meta.get('group_specs','')}",
                run_label=run_dir.name,
                config_summary=f"LED scan, wavelength={meta.get('scan_wavelength','')}, offset={meta.get('ch_offset','')}",
                connection_mode="stimulated_bias_off",
                topology_label="LED scan with bias off",
                technology_layout=infer_technology_layout(run_dir.name, channels),
                selected_dataset_path="",
                selected_setting_kind="grouped_scan",
                selected_setting_value="",
                analysis_status="database_only" if not include else "not_implemented_for_led",
            )
        )

    return records


def merge_lxplus_index(records: list[RunRecord], lxplus_index: dict[str, str]) -> list[RunRecord]:
    by_name = {row.run_name: row for row in records}
    for name, path in lxplus_index.items():
        if name in by_name:
            by_name[name].present_on_lxplus = True
            by_name[name].lxplus_path = path
            continue

        lname = name.lower()
        if not any(token in lname for token in ("nobias", "dark", "bias_off", "noled", "not_connected")):
            continue

        if "osc" in lname:
            kind = "osc"
            stimulus = "osc"
        elif "dark" in lname:
            kind = "dark_vgain"
            stimulus = "dark"
        else:
            kind = "unknown"
            stimulus = "unknown"

        by_name[name] = RunRecord(
            run_name=name,
            run_kind=kind,
            stimulus=stimulus,
            no_bias_status="yes" if any(token in lname for token in ("nobias", "dark", "bias_off", "noled", "not_connected")) else "unknown",
            include_in_noise_analysis=False,
            source_root="lxplus_only",
            local_path="",
            lxplus_path=path,
            present_local=False,
            present_on_lxplus=True,
            channels="",
            waveform_len=0,
            waveforms_per_point=0,
            biasctrl_dac="",
            afe_bias_overrides="",
            notes="Present on lxplus top-level listing only",
            run_label=name,
            config_summary="lxplus-only inventory row",
            connection_mode="unknown",
            topology_label="lxplus-only",
            technology_layout=infer_technology_layout(name, []),
            selected_dataset_path="",
            selected_setting_kind="",
            selected_setting_value="",
            analysis_status="lxplus_only_not_local",
        )
    return sorted(by_name.values(), key=lambda row: (row.run_kind, row.run_name))


def apply_manual_overrides(records: list[RunRecord]) -> list[RunRecord]:
    for record in records:
        override = MANUAL_RUN_OVERRIDES.get(record.run_name)
        if not override:
            continue
        for key, value in override.items():
            if key == "notes_append":
                extra = str(value).strip()
                if extra:
                    record.notes = f"{record.notes}; {extra}" if record.notes else extra
                continue
            setattr(record, key, value)
    return records


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def robust_z(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values.copy()
    med = np.median(values)
    mad = np.median(np.abs(values - med))
    scale = 1.4826 * mad
    if scale <= 0:
        return np.zeros_like(values)
    return (values - med) / scale


def channel_to_afe(channel: int) -> int:
    return int(channel) // 8


def parse_technology_layout_map(layout: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for part in layout.split(","):
        part = part.strip()
        if ":" not in part or not part.startswith("AFE"):
            continue
        lhs, rhs = part.split(":", 1)
        try:
            afe = int(lhs.replace("AFE", ""))
        except Exception:
            continue
        out[afe] = rhs
    return out


def load_dataset_waves(folder: Path, n_samples: int, max_waves: int, interpret: str) -> dict[int, np.ndarray]:
    waves_by_channel: dict[int, np.ndarray] = {}
    for channel in discover_channels(folder):
        path = folder / f"channel_{channel}.dat"
        if not path.exists():
            continue
        try:
            waves_by_channel[channel] = load_channel_waves(path, n_samples, max_waves, interpret)
        except Exception:
            continue
    return waves_by_channel


def corr_summary(channels: list[int], corr: np.ndarray) -> tuple[float, float, float, float, str, float]:
    if corr.size == 0 or len(channels) < 2:
        return math.nan, math.nan, math.nan, math.nan, "", math.nan
    all_vals: list[float] = []
    within: list[float] = []
    cross: list[float] = []
    afe3: list[float] = []
    best_pair = ""
    best_value = -1.0
    for i, ch_a in enumerate(channels):
        for j in range(i + 1, len(channels)):
            ch_b = channels[j]
            value = float(abs(corr[i, j]))
            all_vals.append(value)
            same_afe = channel_to_afe(ch_a) == channel_to_afe(ch_b)
            if same_afe:
                within.append(value)
            else:
                cross.append(value)
            if channel_to_afe(ch_a) == 3 or channel_to_afe(ch_b) == 3:
                afe3.append(value)
            if value > best_value:
                best_value = value
                best_pair = f"ch{ch_a:02d}-ch{ch_b:02d}"
    mean = lambda vals: float(np.mean(vals)) if vals else math.nan
    return mean(all_vals), mean(within), mean(cross), mean(afe3), best_pair, float(best_value)


def analyze_single_record(
    record: RunRecord,
    args: argparse.Namespace,
    metrics_dir: Path,
    plots_dir: Path,
) -> AnalysisResult | None:
    dataset_path = Path(record.selected_dataset_path).expanduser().resolve()
    if not dataset_path.exists():
        return None

    n_samples = int(record.waveform_len)
    if n_samples <= 0:
        meta_json = parse_json(dataset_path / "run_metadata.json")
        n_samples = int(meta_json.get("samples_per_waveform", 0) or 0)
    if n_samples <= 0:
        return None

    waves_by_channel = load_dataset_waves(dataset_path, n_samples, int(args.max_waves), args.interpret)
    if len(waves_by_channel) < 2:
        return None

    channels = sorted(waves_by_channel)
    common_waves = min(arr.shape[0] for arr in waves_by_channel.values())
    if common_waves <= 1:
        return None

    window = get_window(args.fft_window, n_samples)
    metrics_rows: list[dict[str, Any]] = []
    flattened: list[np.ndarray] = []
    fft_by_channel: dict[int, np.ndarray] = {}
    freq_axis: np.ndarray | None = None

    for channel in channels:
        waves = waves_by_channel[channel][:common_waves, :]
        freq_hz, fft_dbfs, used = compute_avg_fft_dbfs(
            waves,
            fs_hz=float(args.fs),
            window=window,
            avg_waves=int(args.fft_avg_waves),
            full_scale_counts=16384.0,
            remove_dc=True,
        )
        row = compute_noise_metrics(waves, freq_hz, fft_dbfs, keep_dc=False)
        row["channel"] = channel
        row["fft_avg_waves_used"] = used
        metrics_rows.append(row)

        ac = waves.astype(np.float64)
        ac -= ac.mean(axis=1, keepdims=True)
        flattened.append(ac.reshape(-1))
        fft_by_channel[channel] = fft_dbfs
        freq_axis = freq_hz

    matrix = np.vstack(flattened)
    corr = np.corrcoef(matrix)
    mean_all, mean_within, mean_cross, mean_afe3, max_pair, max_value = corr_summary(channels, corr)

    metric_fields = ("std_counts", "wf_p2p_mean_counts", "fft_floor_median_dbfs")
    z_payload: dict[str, np.ndarray] = {}
    for field in metric_fields:
        values = np.asarray([float(row[field]) for row in metrics_rows], dtype=float)
        z_payload[field] = robust_z(values)
    outlier_rank: list[tuple[float, int]] = []
    for idx, row in enumerate(metrics_rows):
        zmax = max(abs(float(z_payload[field][idx])) for field in metric_fields)
        row["outlier_score_max_abs_z"] = zmax
        outlier_rank.append((zmax, int(row["channel"])))
    outlier_rank.sort(reverse=True)
    top_outliers = ",".join(f"ch{channel:02d}:{score:.2f}" for score, channel in outlier_rank[:4])

    metrics_rows_sorted = sorted(metrics_rows, key=lambda row: int(row["channel"]))
    metrics_out = metrics_dir / f"{record.run_name}_metrics.csv"
    write_csv(metrics_rows_sorted, metrics_out)

    fig, ax = plt.subplots(figsize=(9.8, 8.2))
    im = ax.imshow(corr, vmin=-0.25, vmax=1.0, cmap="coolwarm")
    ax.set_xticks(range(len(channels)))
    ax.set_xticklabels([str(ch) for ch in channels], rotation=90)
    ax.set_yticks(range(len(channels)))
    ax.set_yticklabels([str(ch) for ch in channels])
    ax.set_title(f"{record.run_name}\nZero-lag AC correlation")
    for boundary in range(8, len(channels), 8):
        ax.axhline(boundary - 0.5, color="black", lw=0.7, alpha=0.45)
        ax.axvline(boundary - 0.5, color="black", lw=0.7, alpha=0.45)
    fig.colorbar(im, ax=ax, label="corrcoef")
    fig.tight_layout()
    heatmap_base = plots_dir / f"{record.run_name}_corr_heatmap"
    fig.savefig(f"{heatmap_base}.png", dpi=180)
    fig.savefig(f"{heatmap_base}.pdf")
    plt.close(fig)

    if freq_axis is not None:
        fig, ax = plt.subplots(figsize=(10.2, 6.2))
        layout_map = parse_technology_layout_map(record.technology_layout)
        for afe in sorted({channel_to_afe(ch) for ch in channels}):
            afe_channels = [ch for ch in channels if channel_to_afe(ch) == afe]
            if not afe_channels:
                continue
            stacked = np.vstack([fft_by_channel[ch] for ch in afe_channels])
            label = layout_map.get(afe, f"AFE{afe}")
            if label.startswith("AFE"):
                label = f"AFE{afe}"
            else:
                label = f"AFE{afe} {label}"
            ax.plot(freq_axis[1:] / 1e6, np.median(stacked, axis=0)[1:], lw=1.6, label=label)
        ax.set_xlabel("Frequency [MHz]")
        ax.set_ylabel("Median FFT [dBFS/bin]")
        ax.set_title(f"{record.run_name}\nMedian FFT by AFE")
        ax.legend(loc="best", frameon=False, fontsize=8)
        ax.grid(True, alpha=0.24)
        fig.tight_layout()
        fft_base = plots_dir / f"{record.run_name}_fft_by_afe"
        fig.savefig(f"{fft_base}.png", dpi=180)
        fig.savefig(f"{fft_base}.pdf")
        plt.close(fig)

    return AnalysisResult(
        run_name=record.run_name,
        run_kind=record.run_kind,
        connection_mode=record.connection_mode,
        topology_label=record.topology_label,
        technology_layout=record.technology_layout,
        selected_dataset_path=str(dataset_path),
        selected_setting_kind=record.selected_setting_kind,
        selected_setting_value=record.selected_setting_value,
        channels=channels,
        mean_abs_corr_all=mean_all,
        mean_abs_corr_within_afe=mean_within,
        mean_abs_corr_cross_afe=mean_cross,
        mean_abs_corr_with_afe3=mean_afe3,
        max_abs_corr_pair=max_pair,
        max_abs_corr_value=max_value,
        median_fft_floor_dbfs=float(np.median([float(row["fft_floor_median_dbfs"]) for row in metrics_rows_sorted])),
        median_fft_peak_dbfs=float(np.median([float(row["fft_peak_dbfs"]) for row in metrics_rows_sorted])),
        median_fft_peak_minus_floor_db=float(np.median([float(row["fft_peak_minus_floor_db"]) for row in metrics_rows_sorted])),
        median_ac_rms_counts=float(np.median([float(row["ac_rms_counts"]) for row in metrics_rows_sorted])),
        top_outlier_channels=top_outliers,
    )


def plot_overview(results: list[AnalysisResult], out_dir: Path) -> None:
    if not results:
        return
    labels = [row.run_name for row in results]
    x = np.arange(len(results))

    fig, axes = plt.subplots(2, 1, figsize=(13.5, 10.5), sharex=True)
    axes[0].bar(x - 0.16, [row.mean_abs_corr_all for row in results], width=0.32, label="All pairs")
    axes[0].bar(x + 0.16, [row.mean_abs_corr_cross_afe for row in results], width=0.32, label="Cross-AFE")
    axes[0].set_ylabel("Mean |corr|")
    axes[0].set_title("No-bias correlation overview")
    axes[0].legend(frameon=False)
    axes[0].grid(True, axis="y", alpha=0.22)

    axes[1].bar(x - 0.18, [row.median_fft_floor_dbfs for row in results], width=0.36, label="Median FFT floor")
    axes[1].bar(x + 0.18, [row.median_fft_peak_minus_floor_db for row in results], width=0.36, label="Peak-floor")
    axes[1].set_ylabel("dB")
    axes[1].legend(frameon=False)
    axes[1].grid(True, axis="y", alpha=0.22)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=85, ha="right", fontsize=8)
    fig.tight_layout()
    base = out_dir / "no_bias_correlation_overview"
    fig.savefig(f"{base}.png", dpi=180)
    fig.savefig(f"{base}.pdf")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    database_dir = output_dir / "database"
    metrics_dir = output_dir / "metrics"
    plots_dir = output_dir / "plots"
    database_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    lxplus_index = load_lxplus_index(Path(args.lxplus_index).expanduser())
    import_root = output_dir / "lxplus_imports"
    records = apply_manual_overrides(merge_lxplus_index(
        build_local_records(int(args.target_vgain), bool(args.include_led_stimulus), import_root),
        lxplus_index,
    ))

    results: list[AnalysisResult] = []
    for record in records:
        if not record.include_in_noise_analysis or not record.present_local:
            continue
        result = analyze_single_record(record, args, metrics_dir, plots_dir)
        if result is not None:
            results.append(result)

    results.sort(key=lambda row: row.run_name)
    analyzed_runs = {row.run_name for row in results}
    for record in records:
        if record.run_name in analyzed_runs:
            record.analysis_status = "analyzed"

    record_rows = [asdict(row) for row in records]
    write_csv(record_rows, database_dir / "run_database.csv")
    (database_dir / "run_database.json").write_text(json.dumps(record_rows, indent=2) + "\n", encoding="utf-8")

    result_rows = []
    for row in results:
        payload = asdict(row)
        payload["channels"] = ",".join(str(ch) for ch in row.channels)
        result_rows.append(payload)

    write_csv(result_rows, output_dir / "crosscorr_summary.csv")
    (output_dir / "crosscorr_summary.json").write_text(json.dumps(result_rows, indent=2) + "\n", encoding="utf-8")
    plot_overview(results, plots_dir)

    print("Saved:")
    print(f"  {database_dir / 'run_database.csv'}")
    print(f"  {output_dir / 'crosscorr_summary.csv'}")
    print(f"  {plots_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
