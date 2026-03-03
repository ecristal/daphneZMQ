#!/usr/bin/env python3
"""
Offline analysis for saved DAPHNE waveform runs.

Features:
- Load channel_<id>.dat files from a run folder.
- Compute average FFT (power-averaged) per channel and plot in overlay mode.
- Compute per-channel noise/shape metrics (RMS, AC RMS, std, p2p, percentiles, etc.).
- Export metrics to CSV/JSON and save figures.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

try:
    from scipy import signal as _scipy_signal
except Exception:
    _scipy_signal = None


METRIC_DESCRIPTIONS = {
    "n_waveforms": "Number of waveforms used from this channel file.",
    "n_samples": "Samples per waveform (record length L).",
    "mean_counts": "Global sample mean (ADC counts).",
    "median_counts": "Global sample median (ADC counts).",
    "std_counts": "Global standard deviation around mean (ADC counts).",
    "ac_rms_counts": "AC RMS after mean removal (noise-like RMS).",
    "rms_counts": "Total RMS including DC offset.",
    "min_counts": "Minimum sample value.",
    "max_counts": "Maximum sample value.",
    "p2p_global_counts": "Global peak-to-peak = max - min.",
    "mad_counts": "Median absolute deviation (robust spread estimator).",
    "p01_counts": "1st percentile of sample distribution.",
    "p05_counts": "5th percentile of sample distribution.",
    "p95_counts": "95th percentile of sample distribution.",
    "p99_counts": "99th percentile of sample distribution.",
    "wf_mean_mean_counts": "Mean of per-waveform means.",
    "wf_mean_std_counts": "Std dev of per-waveform means (baseline drift indicator).",
    "wf_std_mean_counts": "Mean of per-waveform std values.",
    "wf_std_std_counts": "Std dev of per-waveform std values (noise stationarity indicator).",
    "wf_p2p_mean_counts": "Mean of per-waveform peak-to-peak amplitudes.",
    "wf_p2p_std_counts": "Std dev of per-waveform peak-to-peak amplitudes.",
    "skewness": "Distribution asymmetry; 0 is symmetric.",
    "kurtosis_excess": "Tail heaviness vs Gaussian (0 = Gaussian-like).",
    "crest_factor": "0.5*global_p2p / AC_RMS; higher means more impulsive peaks.",
    "fft_peak_freq_hz": "Frequency of strongest FFT bin (after optional DC removal).",
    "fft_peak_dbfs": "Power of strongest FFT bin in dBFS/bin.",
    "fft_floor_median_dbfs": "Median FFT-bin floor in dBFS/bin (excluding peak neighborhood).",
    "fft_floor_mean_dbfs": "Mean FFT-bin floor in dBFS/bin.",
    "fft_peak_minus_floor_db": "Peak-to-floor separation in dB.",
    "fft_avg_waves_used": "Number of waveforms used in FFT averaging.",
    "std_counts_robust_z": "Robust z-score of std_counts vs other channels.",
    "wf_p2p_mean_counts_robust_z": "Robust z-score of mean waveform p2p vs other channels.",
    "fft_floor_median_dbfs_robust_z": "Robust z-score of FFT floor vs other channels.",
    "outlier_score_max_abs_z": "Maximum absolute robust z-score across selected outlier metrics.",
}


def metric_order(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    keys = []
    for k, v in rows[0].items():
        if k == "channel" or isinstance(v, bool):
            continue
        if isinstance(v, (int, float, np.integer, np.floating)):
            keys.append(k)

    preferred = [
        "std_counts",
        "ac_rms_counts",
        "wf_p2p_mean_counts",
        "wf_mean_std_counts",
        "fft_floor_median_dbfs",
        "fft_peak_dbfs",
        "fft_peak_minus_floor_db",
        "skewness",
        "kurtosis_excess",
        "crest_factor",
    ]
    ordered = [k for k in preferred if k in keys]
    ordered.extend(k for k in keys if k not in ordered)
    return ordered


def get_window(name: str, n_samples: int) -> np.ndarray:
    name = name.upper()
    if name == "NONE":
        return np.ones(n_samples, dtype=np.float64)
    if name == "HANNING":
        return np.hanning(n_samples).astype(np.float64)
    if name == "HAMMING":
        return np.hamming(n_samples).astype(np.float64)
    if name == "BLACKMAN":
        return np.blackman(n_samples).astype(np.float64)
    if name == "BLACKMAN-HARRIS":
        if _scipy_signal is None:
            raise RuntimeError("SciPy required for BLACKMAN-HARRIS window.")
        return _scipy_signal.windows.blackmanharris(n_samples).astype(np.float64)
    if name == "TUKEY":
        if _scipy_signal is None:
            raise RuntimeError("SciPy required for TUKEY window.")
        return _scipy_signal.windows.tukey(n_samples, alpha=0.1).astype(np.float64)
    raise ValueError(f"Unknown window: {name}")


def parse_channels_expr(expr: str) -> list[int]:
    out: list[int] = []
    if not expr.strip():
        return out
    for token in expr.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a_str, b_str = token.split("-", 1)
            a = int(a_str)
            b = int(b_str)
            if a > b:
                a, b = b, a
            out.extend(range(a, b + 1))
        else:
            out.append(int(token))
    return sorted(set(out))


def discover_channels(folder: Path) -> list[int]:
    channels: list[int] = []
    rex = re.compile(r"^channel_(\d+)\.dat$")
    for name in os.listdir(folder):
        m = rex.match(name)
        if m:
            channels.append(int(m.group(1)))
    return sorted(set(channels))


def load_metadata(folder: Path) -> dict:
    meta_path = folder / "run_metadata.json"
    if not meta_path.exists():
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            obj = json.load(handle)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _compose_titles(folder: Path, meta: dict, cli_title: str, cli_subtitle: str) -> tuple[str, str]:
    title = (cli_title or "").strip()
    if not title:
        title = str(meta.get("run_label", "")).strip()
    if not title:
        title = folder.name

    subtitle = (cli_subtitle or "").strip()
    if not subtitle:
        subtitle = str(meta.get("run_notes", "")).strip()
    return title, subtitle


def load_channel_waves(path: Path, n_samples: int, max_waves: int, interpret: str) -> np.ndarray:
    raw = np.fromfile(path, dtype=np.uint16)
    if raw.size % n_samples != 0:
        raise ValueError(f"{path}: size {raw.size} not divisible by L={n_samples}")

    n_waves_total = raw.size // n_samples
    n_waves = n_waves_total if max_waves <= 0 else min(n_waves_total, max_waves)
    raw = raw[: n_waves * n_samples]

    if interpret == "signed":
        vals = raw.view(np.int16).astype(np.int32, copy=False)
    else:
        vals = raw.astype(np.int32, copy=False)

    return vals.reshape(n_waves, n_samples)


def compute_avg_fft_dbfs(
    waves: np.ndarray,
    fs_hz: float,
    window: np.ndarray,
    avg_waves: int,
    full_scale_counts: float,
    remove_dc: bool,
) -> tuple[np.ndarray, np.ndarray, int]:
    n_waves = waves.shape[0]
    use_waves = n_waves if avg_waves <= 0 else min(n_waves, avg_waves)

    x = waves[:use_waves, :].astype(np.float64, copy=False)
    if remove_dc:
        x = x - x.mean(axis=1, keepdims=True)

    xw = x * window[np.newaxis, :]
    xf = np.fft.rfft(xw, axis=1)
    power = (xf.real * xf.real + xf.imag * xf.imag) / np.sum(window * window)
    mean_power = power.mean(axis=0)

    dbfs = 10.0 * np.log10((mean_power / (full_scale_counts * full_scale_counts)) + 1e-24)
    freq = np.fft.rfftfreq(waves.shape[1], d=1.0 / fs_hz)
    return freq, dbfs, use_waves


def compute_noise_metrics(
    waves: np.ndarray,
    freq_hz: np.ndarray,
    fft_dbfs: np.ndarray,
    keep_dc: bool,
) -> dict[str, float]:
    x = waves.astype(np.float64, copy=False)
    xr = x.ravel()

    mean = float(xr.mean())
    median = float(np.median(xr))
    std = float(xr.std(ddof=0))
    rms = float(np.sqrt(np.mean(xr * xr)))
    ac_rms = float(np.sqrt(np.mean((xr - mean) * (xr - mean))))
    min_v = float(xr.min())
    max_v = float(xr.max())
    p2p_global = max_v - min_v
    mad = float(np.median(np.abs(xr - median)))
    p01, p05, p95, p99 = np.percentile(xr, [1, 5, 95, 99])

    wf_mean = x.mean(axis=1)
    wf_std = x.std(axis=1)
    wf_p2p = x.max(axis=1) - x.min(axis=1)

    if std > 0:
        z = (xr - mean) / std
        skew = float(np.mean(z ** 3))
        kurtosis_excess = float(np.mean(z ** 4) - 3.0)
    else:
        skew = 0.0
        kurtosis_excess = 0.0

    crest = float((p2p_global * 0.5) / ac_rms) if ac_rms > 0 else float("nan")

    k0 = 0 if keep_dc else 1
    if k0 >= fft_dbfs.size:
        peak_freq_hz = float("nan")
        peak_dbfs = float("nan")
        floor_median_dbfs = float("nan")
        floor_mean_dbfs = float("nan")
        peak_minus_floor_db = float("nan")
    else:
        peak_idx = int(np.argmax(fft_dbfs[k0:]) + k0)
        peak_freq_hz = float(freq_hz[peak_idx])
        peak_dbfs = float(fft_dbfs[peak_idx])

        mask = np.zeros(fft_dbfs.shape, dtype=bool)
        mask[k0:] = True
        lo = max(k0, peak_idx - 1)
        hi = min(fft_dbfs.size, peak_idx + 2)
        mask[lo:hi] = False
        floor_bins = fft_dbfs[mask]
        if floor_bins.size:
            floor_median_dbfs = float(np.median(floor_bins))
            floor_mean_dbfs = float(np.mean(floor_bins))
            peak_minus_floor_db = peak_dbfs - floor_median_dbfs
        else:
            floor_median_dbfs = float("nan")
            floor_mean_dbfs = float("nan")
            peak_minus_floor_db = float("nan")

    return {
        "n_waveforms": int(waves.shape[0]),
        "n_samples": int(waves.shape[1]),
        "mean_counts": mean,
        "median_counts": median,
        "std_counts": std,
        "ac_rms_counts": ac_rms,
        "rms_counts": rms,
        "min_counts": min_v,
        "max_counts": max_v,
        "p2p_global_counts": p2p_global,
        "mad_counts": mad,
        "p01_counts": float(p01),
        "p05_counts": float(p05),
        "p95_counts": float(p95),
        "p99_counts": float(p99),
        "wf_mean_mean_counts": float(np.mean(wf_mean)),
        "wf_mean_std_counts": float(np.std(wf_mean)),
        "wf_std_mean_counts": float(np.mean(wf_std)),
        "wf_std_std_counts": float(np.std(wf_std)),
        "wf_p2p_mean_counts": float(np.mean(wf_p2p)),
        "wf_p2p_std_counts": float(np.std(wf_p2p)),
        "skewness": skew,
        "kurtosis_excess": kurtosis_excess,
        "crest_factor": crest,
        "fft_peak_freq_hz": peak_freq_hz,
        "fft_peak_dbfs": peak_dbfs,
        "fft_floor_median_dbfs": floor_median_dbfs,
        "fft_floor_mean_dbfs": floor_mean_dbfs,
        "fft_peak_minus_floor_db": peak_minus_floor_db,
    }


def sample_ac_points(waves: np.ndarray, max_points: int, rng: np.random.Generator) -> np.ndarray:
    """Return flattened AC-coupled sample points, optionally downsampled."""
    x = waves.astype(np.float64, copy=False)
    x_ac = x - x.mean(axis=1, keepdims=True)
    flat = x_ac.ravel()
    if max_points <= 0 or flat.size <= max_points:
        return flat.copy()
    idx = rng.choice(flat.size, size=max_points, replace=False)
    return flat[idx]


def robust_zscore(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    values = np.asarray(values, dtype=np.float64)
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med)))
    if mad <= 1e-18:
        return np.zeros_like(values, dtype=np.float64), med, mad
    # 0.67449 scales MAD to be comparable to std under normal assumptions.
    z = 0.67448975 * (values - med) / mad
    return z, med, mad


def mark_outliers(metrics_rows: list[dict], z_threshold: float) -> list[tuple[int, str]]:
    """
    Mark outlier channels using robust z-score across channels.
    Returns list of (channel, reason_string) flagged as outliers.
    """
    for row in metrics_rows:
        row["outlier_score_max_abs_z"] = 0.0
        row["outlier_flag"] = False
        row["outlier_reasons"] = ""

    if z_threshold <= 0 or len(metrics_rows) < 4:
        return []

    metrics_for_outlier = [
        "std_counts",
        "wf_p2p_mean_counts",
        "fft_floor_median_dbfs",
    ]

    z_map: dict[str, np.ndarray] = {}
    for key in metrics_for_outlier:
        vals = np.array([float(r[key]) for r in metrics_rows], dtype=np.float64)
        z, _med, _mad = robust_zscore(vals)
        z_map[key] = z

    flagged: list[tuple[int, str]] = []
    for i, row in enumerate(metrics_rows):
        reasons: list[str] = []
        z_max = 0.0
        for key in metrics_for_outlier:
            z_val = float(z_map[key][i])
            row[f"{key}_robust_z"] = z_val
            z_abs = abs(z_val)
            z_max = max(z_max, z_abs)
            if z_abs >= z_threshold:
                reasons.append(f"{key}:z={z_val:+.2f}")
        row["outlier_score_max_abs_z"] = z_max
        row["outlier_flag"] = bool(reasons)
        row["outlier_reasons"] = "; ".join(reasons)
        if reasons:
            flagged.append((int(row["channel"]), row["outlier_reasons"]))
    return flagged


def save_metrics(metrics_rows: list[dict], csv_path: Path, json_path: Path) -> None:
    if not metrics_rows:
        return
    keys = list(metrics_rows[0].keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(metrics_rows)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(metrics_rows, handle, indent=2)


def _json_safe(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return None
    return value


def write_interactive_html(metrics_rows: list[dict], html_path: Path, dataset_name: str) -> None:
    if not metrics_rows:
        return

    rows = []
    for r in metrics_rows:
        rows.append({k: _json_safe(v) for k, v in r.items()})

    m_order = metric_order(metrics_rows)
    payload_rows = json.dumps(rows)
    payload_desc = json.dumps(METRIC_DESCRIPTIONS)
    payload_order = json.dumps(m_order)
    dataset_escaped = dataset_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Noise Metrics Explorer - {dataset_escaped}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      margin: 20px;
      color: #111827;
      background: #f8fafc;
    }}
    .panel {{
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      padding: 14px;
      margin-bottom: 14px;
      box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }}
    .row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    select, button {{
      font-size: 14px;
      padding: 7px 10px;
      border-radius: 8px;
      border: 1px solid #cbd5e1;
      background: #fff;
    }}
    button {{
      cursor: pointer;
      background: #f1f5f9;
    }}
    #chartWrap {{
      position: relative;
      height: 520px;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      background: #fff;
      overflow: hidden;
    }}
    #chart {{
      width: 100%;
      height: 100%;
      display: block;
    }}
    #tooltip {{
      position: absolute;
      pointer-events: none;
      display: none;
      background: rgba(17, 24, 39, 0.92);
      color: #fff;
      padding: 8px 10px;
      border-radius: 8px;
      font-size: 12px;
      max-width: 340px;
      white-space: pre-wrap;
      z-index: 10;
    }}
    .muted {{
      color: #475569;
      font-size: 13px;
    }}
    #stats {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      font-size: 12px;
      color: #334155;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 8px;
      margin-top: 10px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
      padding: 6px 8px;
    }}
    th {{
      background: #f8fafc;
      position: sticky;
      top: 0;
    }}
    .outlier {{
      color: #b91c1c;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <div class="panel">
    <div class="row">
      <h2 style="margin:0;">Noise Metrics Explorer</h2>
      <span class="muted">Dataset: {dataset_escaped}</span>
    </div>
    <div class="row" style="margin-top:10px;">
      <label for="metricSelect"><strong>Metric</strong></label>
      <button id="prevBtn" type="button">Prev</button>
      <select id="metricSelect"></select>
      <button id="nextBtn" type="button">Next</button>
      <label style="display:flex;align-items:center;gap:6px;margin-left:8px;">
        <input id="logY" type="checkbox" />
        Log Y
      </label>
    </div>
    <div id="metricDesc" class="muted" style="margin-top:8px;"></div>
    <div id="stats"></div>
  </div>

  <div class="panel">
    <div id="chartWrap">
      <svg id="chart" viewBox="0 0 1200 520" preserveAspectRatio="none"></svg>
      <div id="tooltip"></div>
    </div>
  </div>

  <div class="panel">
    <h3 style="margin-top:0;">Channel Values</h3>
    <div style="max-height:300px; overflow:auto;">
      <table>
        <thead>
          <tr>
            <th>Channel</th>
            <th>Value</th>
            <th>Outlier</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>
  </div>

  <script>
    const rows = {payload_rows};
    const metricDescriptions = {payload_desc};
    const metricOrder = {payload_order};

    const chart = document.getElementById("chart");
    const tooltip = document.getElementById("tooltip");
    const select = document.getElementById("metricSelect");
    const metricDesc = document.getElementById("metricDesc");
    const statsEl = document.getElementById("stats");
    const tableBody = document.getElementById("tableBody");
    const logYEl = document.getElementById("logY");

    function toNum(v) {{
      return (v === null || v === undefined) ? NaN : Number(v);
    }}

    function finiteVals(arr) {{
      return arr.filter(v => Number.isFinite(v));
    }}

    function median(arr) {{
      const a = [...arr].sort((x, y) => x - y);
      if (a.length === 0) return NaN;
      const m = Math.floor(a.length / 2);
      return (a.length % 2) ? a[m] : 0.5 * (a[m - 1] + a[m]);
    }}

    function mean(arr) {{
      if (!arr.length) return NaN;
      return arr.reduce((s, v) => s + v, 0) / arr.length;
    }}

    function std(arr) {{
      if (!arr.length) return NaN;
      const m = mean(arr);
      const v = mean(arr.map(x => (x - m) * (x - m)));
      return Math.sqrt(v);
    }}

    function fmt(v) {{
      if (!Number.isFinite(v)) return "n/a";
      const av = Math.abs(v);
      if ((av >= 10000) || (av > 0 && av < 0.01)) return v.toExponential(3);
      return v.toFixed(4);
    }}

    function make(tag, attrs = {{}}, parent = null) {{
      const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
      if (parent) parent.appendChild(el);
      return el;
    }}

    function renderTable(metric, points) {{
      tableBody.innerHTML = "";
      for (const p of points) {{
        const tr = document.createElement("tr");
        const out = p.outlier ? "YES" : "no";
        tr.innerHTML =
          `<td>${{p.channel}}</td>` +
          `<td>${{fmt(p.value)}}</td>` +
          `<td class="${{p.outlier ? "outlier" : ""}}">${{out}}</td>` +
          `<td>${{p.reason || ""}}</td>`;
        tableBody.appendChild(tr);
      }}
    }}

    function showTooltip(evt, text) {{
      tooltip.style.display = "block";
      tooltip.textContent = text;
      const pad = 12;
      const rect = chart.getBoundingClientRect();
      const x = evt.clientX - rect.left + pad;
      const y = evt.clientY - rect.top + pad;
      tooltip.style.left = `${{Math.min(x, rect.width - 320)}}px`;
      tooltip.style.top = `${{Math.min(y, rect.height - 120)}}px`;
    }}

    function hideTooltip() {{
      tooltip.style.display = "none";
    }}

    function render() {{
      const metric = select.value;
      const useLog = logYEl.checked;
      const points = rows
        .map(r => ({{
          channel: Number(r.channel),
          value: toNum(r[metric]),
          outlier: !!r.outlier_flag,
          reason: r.outlier_reasons || "",
        }}))
        .sort((a, b) => a.channel - b.channel);

      const vals = finiteVals(points.map(p => p.value));
      const chVals = points.map(p => p.channel);
      if (!vals.length || !chVals.length) return;

      let yVals = vals;
      if (useLog) {{
        yVals = vals.filter(v => v > 0).map(v => Math.log10(v));
      }}
      if (!yVals.length) {{
        statsEl.textContent = "Cannot use log scale for this metric (no positive values).";
        return;
      }}

      let yMin = Math.min(...yVals);
      let yMax = Math.max(...yVals);
      if (yMin === yMax) {{
        yMin -= 1.0;
        yMax += 1.0;
      }}
      const xMin = Math.min(...chVals);
      const xMax = Math.max(...chVals);

      const W = 1200, H = 520;
      const L = 70, R = 20, T = 24, B = 56;
      const plotW = W - L - R;
      const plotH = H - T - B;

      const xScale = (x) => (xMax === xMin) ? (L + plotW * 0.5) : (L + (x - xMin) * plotW / (xMax - xMin));
      const yScale = (y) => T + (yMax - y) * plotH / (yMax - yMin);
      const yMetric = (v) => useLog ? Math.log10(v) : v;

      chart.innerHTML = "";
      make("rect", {{x:0, y:0, width:W, height:H, fill:"#ffffff"}}, chart);

      // horizontal grid + y ticks
      const nGrid = 6;
      for (let i = 0; i <= nGrid; i++) {{
        const frac = i / nGrid;
        const y = T + frac * plotH;
        const yVal = yMax - frac * (yMax - yMin);
        make("line", {{x1:L, y1:y, x2:L+plotW, y2:y, stroke:"#e2e8f0", "stroke-width":"1"}}, chart);
        const label = useLog ? Math.pow(10, yVal) : yVal;
        const txt = make("text", {{x:L-8, y:y+4, "text-anchor":"end", fill:"#334155", "font-size":"11"}}, chart);
        txt.textContent = fmt(label);
      }}

      // axes
      make("line", {{x1:L, y1:T+plotH, x2:L+plotW, y2:T+plotH, stroke:"#334155", "stroke-width":"1.5"}}, chart);
      make("line", {{x1:L, y1:T, x2:L, y2:T+plotH, stroke:"#334155", "stroke-width":"1.5"}}, chart);

      // x ticks
      for (const ch of chVals) {{
        const x = xScale(ch);
        make("line", {{x1:x, y1:T+plotH, x2:x, y2:T+plotH+6, stroke:"#334155", "stroke-width":"1"}}, chart);
        const txt = make("text", {{x:x, y:T+plotH+20, "text-anchor":"middle", fill:"#334155", "font-size":"11"}}, chart);
        txt.textContent = ch.toString();
      }}

      // line path
      const inRangePts = points.filter(p => Number.isFinite(p.value) && (!useLog || p.value > 0));
      const pathD = inRangePts.map((p, i) => `${{i ? "L" : "M"}} ${{xScale(p.channel)}} ${{yScale(yMetric(p.value))}}`).join(" ");
      if (pathD) {{
        make("path", {{d:pathD, fill:"none", stroke:"#0f766e", "stroke-width":"2"}}, chart);
      }}

      // points
      for (const p of inRangePts) {{
        const cx = xScale(p.channel);
        const cy = yScale(yMetric(p.value));
        const color = p.outlier ? "#dc2626" : "#0f766e";
        const c = make("circle", {{cx, cy, r:4.2, fill:color, stroke:"#ffffff", "stroke-width":"1.2"}}, chart);
        c.addEventListener("mousemove", (evt) => {{
          const txt = `ch${{p.channel}}\\n${{metric}} = ${{fmt(p.value)}}` +
            (p.outlier ? `\\noutlier: YES\\n${{p.reason}}` : "");
          showTooltip(evt, txt);
        }});
        c.addEventListener("mouseleave", hideTooltip);
      }}

      const summary = [
        `metric: ${{metric}}`,
        `min=${{fmt(Math.min(...vals))}}`,
        `max=${{fmt(Math.max(...vals))}}`,
        `mean=${{fmt(mean(vals))}}`,
        `median=${{fmt(median(vals))}}`,
        `std=${{fmt(std(vals))}}`,
        `outliers=${{points.filter(p => p.outlier).length}}/${{points.length}}`,
      ];
      statsEl.textContent = summary.join("   ");

      metricDesc.textContent = metricDescriptions[metric] || "";
      renderTable(metric, points);
    }}

    for (const key of metricOrder) {{
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = key;
      select.appendChild(opt);
    }}
    if (metricOrder.includes("std_counts")) {{
      select.value = "std_counts";
    }}

    document.getElementById("prevBtn").addEventListener("click", () => {{
      const idx = metricOrder.indexOf(select.value);
      const next = (idx <= 0) ? metricOrder.length - 1 : idx - 1;
      select.value = metricOrder[next];
      render();
    }});
    document.getElementById("nextBtn").addEventListener("click", () => {{
      const idx = metricOrder.indexOf(select.value);
      const next = (idx + 1) % metricOrder.length;
      select.value = metricOrder[next];
      render();
    }});
    select.addEventListener("change", render);
    logYEl.addEventListener("change", render);
    window.addEventListener("resize", render);

    render();
  </script>
</body>
</html>
"""
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(html)


def print_summary(metrics_rows: list[dict]) -> None:
    if not metrics_rows:
        print("No metrics to show.")
        return
    print(
        "channel  n_waves  mean      std       ac_rms    p2p_mean  p2p_global  "
        "fft_peak_dbfs  fft_floor_dbfs  outlier"
    )
    for row in metrics_rows:
        out = "YES" if bool(row.get("outlier_flag", False)) else "no"
        print(
            f"{int(row['channel']):>7d}  "
            f"{int(row['n_waveforms']):>7d}  "
            f"{row['mean_counts']:>8.2f}  "
            f"{row['std_counts']:>8.2f}  "
            f"{row['ac_rms_counts']:>8.2f}  "
            f"{row['wf_p2p_mean_counts']:>8.2f}  "
            f"{row['p2p_global_counts']:>10.2f}  "
            f"{row['fft_peak_dbfs']:>13.2f}  "
            f"{row['fft_floor_median_dbfs']:>14.2f}  "
            f"{out:>7s}"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze saved DAPHNE waveforms and plot FFT overlays + noise metrics.")
    ap.add_argument("--folder", required=True, help="Run folder containing channel_<id>.dat files")
    ap.add_argument("--channels", default="", help="Channels CSV/range, e.g. '0-7,10' (default: metadata or auto-discover)")
    ap.add_argument("-L", type=int, default=0, help="Samples per waveform (default: read from run_metadata.json)")
    ap.add_argument("--fs", type=float, default=0.0, help="Sampling rate in Hz (default: run_metadata or 62.5e6)")
    ap.add_argument("--max_waves", type=int, default=0, help="Max waveforms loaded per channel (0 = all)")
    ap.add_argument("--fft_avg_waves", type=int, default=0, help="Waveforms to average in FFT (0 = all loaded)")
    ap.add_argument(
        "--fft_window",
        type=str,
        default="",
        choices=["", "NONE", "HANNING", "HAMMING", "BLACKMAN", "BLACKMAN-HARRIS", "TUKEY"],
        help="FFT window (default: run_metadata or BLACKMAN-HARRIS)",
    )
    ap.add_argument("--fft_full_scale_counts", type=float, default=16384.0, help="Full-scale counts for dBFS")
    ap.add_argument("--fft_keep_dc", action="store_true", help="Keep DC in FFT metrics/plots")
    ap.add_argument("--fft_log_x", action="store_true", help="Use logarithmic frequency axis in FFT overlay plot")
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed", help="Interpret stored uint16 samples")
    ap.add_argument("--hist_bins", type=int, default=180, help="Bins for AC-noise histogram overlay")
    ap.add_argument(
        "--hist_sample_points",
        type=int,
        default=300000,
        help="Max AC points per channel in histogram overlay (0 = all)",
    )
    ap.add_argument(
        "--outlier_z",
        type=float,
        default=3.5,
        help="Robust z-score threshold for outlier channel flagging (<=0 disables)",
    )
    ap.add_argument("--no-show", action="store_true", help="Do not open interactive figures")
    ap.add_argument("--prefix", type=str, default="", help="Prefix for output files")
    ap.add_argument("--title", type=str, default="", help="Human-readable dataset title for plots/HTML")
    ap.add_argument("--subtitle", type=str, default="", help="Optional subtitle/notes line for plots/HTML")
    args = ap.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.exists():
        print(f"Folder not found: {folder}")
        return 2
    if args.hist_bins < 10:
        print("hist_bins must be >= 10")
        return 2
    if args.hist_sample_points < 0:
        print("hist_sample_points must be >= 0")
        return 2

    meta = load_metadata(folder)
    plot_title, plot_subtitle = _compose_titles(folder, meta, args.title, args.subtitle)

    channels = parse_channels_expr(args.channels) if args.channels else []
    if not channels and isinstance(meta.get("channels"), list):
        try:
            channels = sorted(set(int(c) for c in meta["channels"]))
        except Exception:
            channels = []
    if not channels:
        channels = discover_channels(folder)
    if not channels:
        print("No channels found. Provide --channels or check channel_<id>.dat files.")
        return 2

    n_samples = int(args.L) if args.L > 0 else int(meta.get("samples_per_waveform", 0) or 0)
    if n_samples <= 0:
        print("Samples per waveform unknown. Provide -L.")
        return 2

    fs_hz = float(args.fs) if args.fs > 0 else float(meta.get("sampling_rate_hz", 62.5e6))
    fft_window_name = args.fft_window if args.fft_window else str(meta.get("fft_window_function", "BLACKMAN-HARRIS"))
    window = get_window(fft_window_name, n_samples)
    keep_dc = bool(args.fft_keep_dc)

    overlay_fft: list[tuple[int, np.ndarray, np.ndarray]] = []
    metrics_rows: list[dict] = []
    hist_samples: dict[int, np.ndarray] = {}
    rng = np.random.default_rng(12345)

    for ch in channels:
        path = folder / f"channel_{ch}.dat"
        if not path.exists():
            print(f"[skip] missing {path.name}")
            continue

        waves = load_channel_waves(path, n_samples=n_samples, max_waves=args.max_waves, interpret=args.interpret)
        if waves.size == 0:
            print(f"[skip] empty {path.name}")
            continue

        freq_hz, fft_dbfs, fft_used = compute_avg_fft_dbfs(
            waves,
            fs_hz=fs_hz,
            window=window,
            avg_waves=args.fft_avg_waves,
            full_scale_counts=args.fft_full_scale_counts,
            remove_dc=(not keep_dc),
        )
        row = compute_noise_metrics(waves, freq_hz, fft_dbfs, keep_dc=keep_dc)
        row["channel"] = int(ch)
        row["fft_avg_waves_used"] = int(fft_used)
        metrics_rows.append(row)
        overlay_fft.append((int(ch), freq_hz, fft_dbfs))
        hist_samples[int(ch)] = sample_ac_points(waves, max_points=args.hist_sample_points, rng=rng)

    if not metrics_rows:
        print("No valid channel data was loaded.")
        return 2

    metrics_rows.sort(key=lambda d: int(d["channel"]))
    overlay_fft.sort(key=lambda t: int(t[0]))
    flagged = mark_outliers(metrics_rows, z_threshold=float(args.outlier_z))

    print_summary(metrics_rows)
    if flagged:
        print("\nOutlier channels:")
        for ch, reasons in flagged:
            print(f"  ch{ch:02d}: {reasons}")

    prefix = args.prefix if args.prefix else ""
    fft_overlay_path = folder / f"{prefix}fft_overlay.png"
    hist_overlay_path = folder / f"{prefix}noise_hist_overlay.png"
    noise_summary_path = folder / f"{prefix}noise_summary.png"
    csv_path = folder / f"{prefix}noise_metrics.csv"
    json_path = folder / f"{prefix}noise_metrics.json"
    html_path = folder / f"{prefix}noise_metrics_interactive.html"

    # FFT overlay figure
    fig_fft, ax_fft = plt.subplots(figsize=(12, 7))
    k0 = 0 if keep_dc else (4 if (overlay_fft[0][1].size > 4) else 0)
    if args.fft_log_x:
        # Log-x cannot include DC bin.
        k0 = max(k0, 1)
    for ch, f_hz, dbfs in overlay_fft:
        fx = f_hz[k0:] / 1e6
        fy = dbfs[k0:]
        if args.fft_log_x:
            mask = fx > 0
            fx = fx[mask]
            fy = fy[mask]
        if fx.size == 0:
            continue
        ax_fft.plot(fx, fy, lw=1.0, label=f"ch{ch}")
    if args.fft_log_x:
        ax_fft.set_xscale("log")
    ax_fft.set_title(f"Average FFT Overlay ({plot_title})")
    ax_fft.set_xlabel("Frequency [MHz]" + (" (log)" if args.fft_log_x else ""))
    ax_fft.set_ylabel("Power [dBFS/bin]")
    ax_fft.grid(True, which="both" if args.fft_log_x else "major", alpha=0.35)
    ax_fft.legend(ncol=max(1, min(8, len(overlay_fft) // 2 + 1)), fontsize=8, loc="best")
    if plot_subtitle:
        fig_fft.text(0.5, 0.008, plot_subtitle, ha="center", va="bottom", fontsize=8, wrap=True)
        fig_fft.tight_layout(rect=(0, 0.03, 1, 1))
    else:
        fig_fft.tight_layout()
    fig_fft.savefig(fft_overlay_path, dpi=150)

    # AC-noise histogram overlay
    fig_hist, ax_hist = plt.subplots(figsize=(12, 7))
    for ch, _f_hz, _dbfs in overlay_fft:
        samples = hist_samples.get(int(ch))
        if samples is None or samples.size == 0:
            continue
        ax_hist.hist(
            samples,
            bins=args.hist_bins,
            density=True,
            histtype="step",
            linewidth=1.2,
            alpha=0.95,
            label=f"ch{ch}",
        )
    ax_hist.set_title(f"AC Noise Histogram Overlay ({plot_title})")
    ax_hist.set_xlabel("ADC counts (AC-coupled)")
    ax_hist.set_ylabel("Density")
    ax_hist.grid(True, alpha=0.35)
    ax_hist.legend(ncol=max(1, min(8, len(overlay_fft) // 2 + 1)), fontsize=8, loc="best")
    if plot_subtitle:
        fig_hist.text(0.5, 0.008, plot_subtitle, ha="center", va="bottom", fontsize=8, wrap=True)
        fig_hist.tight_layout(rect=(0, 0.03, 1, 1))
    else:
        fig_hist.tight_layout()
    fig_hist.savefig(hist_overlay_path, dpi=150)

    # Noise summary figure
    chs = [int(r["channel"]) for r in metrics_rows]
    std_vals = [float(r["std_counts"]) for r in metrics_rows]
    p2p_vals = [float(r["wf_p2p_mean_counts"]) for r in metrics_rows]
    floor_vals = [float(r["fft_floor_median_dbfs"]) for r in metrics_rows]

    fig_noise, axs = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    axs[0].plot(chs, std_vals, marker="o")
    axs[0].set_ylabel("STD [counts]")
    axs[0].grid(True, alpha=0.3)
    axs[0].set_title(f"Per-Channel Noise Summary ({plot_title})")

    axs[1].plot(chs, p2p_vals, marker="o")
    axs[1].set_ylabel("Mean P2P [counts]")
    axs[1].grid(True, alpha=0.3)

    axs[2].plot(chs, floor_vals, marker="o")
    axs[2].set_ylabel("FFT Floor [dBFS]")
    axs[2].set_xlabel("Channel")
    axs[2].grid(True, alpha=0.3)
    if plot_subtitle:
        fig_noise.text(0.5, 0.008, plot_subtitle, ha="center", va="bottom", fontsize=8, wrap=True)
        fig_noise.tight_layout(rect=(0, 0.03, 1, 1))
    else:
        fig_noise.tight_layout()
    fig_noise.savefig(noise_summary_path, dpi=150)

    save_metrics(metrics_rows, csv_path, json_path)
    html_dataset_name = plot_title if not plot_subtitle else f"{plot_title} — {plot_subtitle}"
    write_interactive_html(metrics_rows, html_path=html_path, dataset_name=html_dataset_name)

    print(f"\nSaved:")
    print(f"  {fft_overlay_path}")
    print(f"  {hist_overlay_path}")
    print(f"  {noise_summary_path}")
    print(f"  {csv_path}")
    print(f"  {json_path}")
    print(f"  {html_path}")

    if not args.no_show:
        plt.show()
    else:
        plt.close(fig_fft)
        plt.close(fig_hist)
        plt.close(fig_noise)

    return 0


if __name__ == "__main__":
    sys.exit(main())
