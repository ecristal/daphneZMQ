#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from plotly.offline import get_plotlyjs

ROOT_DIR = Path(__file__).resolve().parents[1]

import sys

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from client.analyze_waveform_dataset import (  # noqa: E402
    compute_avg_fft_dbfs,
    discover_channels,
    get_window,
    load_channel_waves,
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build a self-contained Plotly FFT selector HTML for analyzed no-bias runs."
    )
    ap.add_argument("--database-csv", required=True, help="Path to run_database.csv")
    ap.add_argument("--summary-csv", required=True, help="Path to crosscorr_summary.csv")
    ap.add_argument("--output-html", required=True, help="Output HTML file")
    ap.add_argument("--max-waves", type=int, default=256, help="Waveforms loaded per channel")
    ap.add_argument("--fft-avg-waves", type=int, default=256, help="Waveforms averaged in FFT")
    ap.add_argument("--fft-window", default="BLACKMAN-HARRIS", help="FFT window name")
    ap.add_argument("--fs", type=float, default=62.5e6, help="Sampling rate in Hz")
    ap.add_argument("--interpret", choices=["signed", "unsigned"], default="signed")
    ap.add_argument("--max-freq-points", type=int, default=600, help="Optional decimation cap per FFT trace")
    ap.add_argument("--title", default="No-Bias FFT Selector", help="HTML title")
    return ap.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def to_float(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return math.nan


def channel_to_afe(channel: int) -> int:
    return int(channel) // 8


def parse_layout_map(layout: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for part in layout.split(","):
        part = part.strip()
        if not part.startswith("AFE") or ":" not in part:
            continue
        lhs, rhs = part.split(":", 1)
        try:
            afe = int(lhs.replace("AFE", ""))
        except Exception:
            continue
        out[afe] = rhs.strip()
    return out


def merge_rows(database_rows: list[dict[str, str]], summary_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    db_by_name = {row["run_name"]: row for row in database_rows}
    merged: list[dict[str, Any]] = []
    for row in summary_rows:
        db = db_by_name.get(row["run_name"], {})
        merged.append(
            {
                "run_name": row["run_name"],
                "run_kind": row["run_kind"],
                "connection_mode": row["connection_mode"],
                "topology_label": row["topology_label"],
                "technology_layout": row["technology_layout"],
                "selected_dataset_path": row["selected_dataset_path"],
                "selected_setting_kind": row["selected_setting_kind"],
                "selected_setting_value": row["selected_setting_value"],
                "channels": row["channels"],
                "source_root": db.get("source_root", ""),
                "analysis_status": db.get("analysis_status", ""),
                "config_summary": db.get("config_summary", ""),
                "notes": db.get("notes", ""),
                "waveform_len": int(db.get("waveform_len", "0") or 0),
                "mean_abs_corr_cross_afe": to_float(row.get("mean_abs_corr_cross_afe", "")),
                "max_abs_corr_value": to_float(row.get("max_abs_corr_value", "")),
                "median_fft_floor_dbfs": to_float(row.get("median_fft_floor_dbfs", "")),
                "median_ac_rms_counts": to_float(row.get("median_ac_rms_counts", "")),
            }
        )
    return [row for row in merged if row["analysis_status"] == "analyzed"]


def load_fft_traces(row: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    dataset_path = Path(str(row["selected_dataset_path"])).expanduser().resolve()
    if not dataset_path.exists():
        return []

    n_samples = int(row["waveform_len"] or 0)
    if n_samples <= 0:
        return []

    window = get_window(str(args.fft_window), n_samples)
    afe_map = parse_layout_map(str(row["technology_layout"]))
    by_afe: dict[int, list[np.ndarray]] = {}
    freq_axis: np.ndarray | None = None

    for channel in discover_channels(dataset_path):
        path = dataset_path / f"channel_{channel}.dat"
        if not path.exists():
            continue
        try:
            waves = load_channel_waves(path, n_samples, int(args.max_waves), str(args.interpret))
        except Exception:
            continue
        freq_hz, fft_dbfs, _used = compute_avg_fft_dbfs(
            waves,
            fs_hz=float(args.fs),
            window=window,
            avg_waves=int(args.fft_avg_waves),
            full_scale_counts=16384.0,
            remove_dc=True,
        )
        by_afe.setdefault(channel_to_afe(channel), []).append(fft_dbfs)
        if freq_axis is None:
            freq_axis = freq_hz

    if freq_axis is None:
        return []

    step = max(1, int(math.ceil(len(freq_axis) / max(1, int(args.max_freq_points)))))
    freq_mhz = (freq_axis[::step] / 1e6).tolist()
    traces: list[dict[str, Any]] = []
    for afe in sorted(by_afe):
        median_curve = np.median(np.vstack(by_afe[afe]), axis=0)
        afe_label = afe_map.get(afe, "")
        label = f"AFE{afe}" if not afe_label else f"AFE{afe} {afe_label}"
        traces.append(
            {
                "run_name": row["run_name"],
                "run_kind": row["run_kind"],
                "connection_mode": row["connection_mode"],
                "topology_label": row["topology_label"],
                "technology_layout": row["technology_layout"],
                "afe": afe,
                "afe_label": label,
                "freq_mhz": freq_mhz,
                "fft_dbfs": median_curve[::step].tolist(),
                "selected_setting_kind": row["selected_setting_kind"],
                "selected_setting_value": row["selected_setting_value"],
                "source_root": row["source_root"],
                "config_summary": row["config_summary"],
                "notes": row["notes"],
                "mean_abs_corr_cross_afe": row["mean_abs_corr_cross_afe"],
                "max_abs_corr_value": row["max_abs_corr_value"],
                "median_fft_floor_dbfs": row["median_fft_floor_dbfs"],
                "median_ac_rms_counts": row["median_ac_rms_counts"],
            }
        )
    return traces


def build_html(title: str, rows: list[dict[str, Any]], traces: list[dict[str, Any]]) -> str:
    rows_by_name = {row["run_name"]: row for row in rows}
    vgain_values = sorted(
        {
            str(row["selected_setting_value"])
            for row in rows
            if str(row.get("selected_setting_kind", "")) == "vgain" and str(row.get("selected_setting_value", "")) != ""
        },
        key=lambda value: float(value),
    )
    plotly_js = get_plotlyjs()
    traces_json = json.dumps(traces, ensure_ascii=True)
    rows_json = json.dumps(rows_by_name, ensure_ascii=True)
    rows_list_json = json.dumps(rows, ensure_ascii=True)
    vgain_options = ['<option value="all" selected>All</option>']
    if any(str(row.get("selected_setting_kind", "")) != "vgain" or str(row.get("selected_setting_value", "")) == "" for row in rows):
        vgain_options.append('<option value="fixed">Fixed / other</option>')
    for value in vgain_values:
        vgain_options.append(f'<option value="{html.escape(value)}">{html.escape(value)}</option>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: #f3f5f7;
      color: #1f2933;
    }}
    .wrap {{
      display: grid;
      grid-template-columns: 360px 1fr;
      min-height: 100vh;
    }}
    .sidebar {{
      border-right: 1px solid #d9e2ec;
      background: #ffffff;
      padding: 18px;
      overflow: auto;
    }}
    .main {{
      padding: 18px;
      overflow: auto;
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
    }}
    .hint {{
      margin: 0 0 14px;
      color: #52606d;
      font-size: 13px;
    }}
    select, button {{
      width: 100%;
      margin-bottom: 10px;
      font-family: inherit;
      font-size: 13px;
    }}
    select[multiple] {{
      height: 420px;
    }}
    .btnrow {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .card {{
      background: #ffffff;
      border: 1px solid #d9e2ec;
      padding: 12px 14px;
      margin-bottom: 14px;
    }}
    .meta {{
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
    }}
    #plot {{
      width: 100%;
      height: 82vh;
      background: white;
      border: 1px solid #d9e2ec;
    }}
  </style>
  <script>{plotly_js}</script>
</head>
<body>
  <div class="wrap">
    <div class="sidebar">
      <h1>{html.escape(title)}</h1>
      <div class="hint">Select a few runs, choose an AFE filter, then compare median FFT curves. Same color means same run; dash style encodes AFE.</div>
      <label for="vgainFilter"><b>Representative vgain</b></label>
      <select id="vgainFilter">
        {''.join(vgain_options)}
      </select>
      <label for="runSelect"><b>Runs</b></label>
      <select id="runSelect" multiple>
      </select>
      <div class="btnrow">
        <button type="button" onclick="selectAllRuns()">Select All</button>
        <button type="button" onclick="clearRuns()">Clear</button>
      </div>
      <label for="afeFilter"><b>AFE filter</b></label>
      <select id="afeFilter">
        <option value="all" selected>All AFEs</option>
        <option value="0">AFE0</option>
        <option value="1">AFE1</option>
        <option value="2">AFE2</option>
        <option value="3">AFE3</option>
      </select>
      <label for="xScale"><b>Frequency scale</b></label>
      <select id="xScale">
        <option value="linear" selected>Linear</option>
        <option value="log">Log</option>
      </select>
      <div class="card">
        <h3>Selected Runs</h3>
        <div id="runMeta" class="meta">Select one or more runs.</div>
      </div>
    </div>
    <div class="main">
      <div id="plot"></div>
    </div>
  </div>
  <script>
    const traceData = {traces_json};
    const runMeta = {rows_json};
    const runRows = {rows_list_json};
    const colorPalette = [
      "#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf",
      "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#003f5c", "#7a5195",
      "#ef5675", "#ffa600", "#2f4b7c", "#665191", "#a05195", "#d45087"
    ];
    const dashMap = {{
      "0": "solid",
      "1": "dot",
      "2": "dash",
      "3": "dashdot"
    }};

    function rowMatchesVgain(row, vgainFilter) {{
      if (vgainFilter === "all") return true;
      if (vgainFilter === "fixed") {{
        return row.selected_setting_kind !== "vgain" || !String(row.selected_setting_value || "").length;
      }}
      return String(row.selected_setting_value) === vgainFilter;
    }}

    function getSelectedRuns() {{
      const select = document.getElementById("runSelect");
      return Array.from(select.selectedOptions).map(opt => opt.value);
    }}

    function refreshRunOptions() {{
      const select = document.getElementById("runSelect");
      const vgainFilter = document.getElementById("vgainFilter").value;
      const previous = new Set(getSelectedRuns());
      const filtered = runRows.filter(row => rowMatchesVgain(row, vgainFilter));

      select.innerHTML = "";
      filtered.forEach((row, idx) => {{
        const opt = document.createElement("option");
        opt.value = row.run_name;
        opt.textContent = row.run_name + " | " + row.connection_mode;
        if (previous.has(row.run_name)) {{
          opt.selected = true;
        }}
        select.appendChild(opt);
      }});

      if (!Array.from(select.options).some(opt => opt.selected)) {{
        Array.from(select.options).slice(0, 4).forEach(opt => {{
          opt.selected = true;
        }});
      }}
    }}

    function selectAllRuns() {{
      const select = document.getElementById("runSelect");
      Array.from(select.options).forEach(opt => opt.selected = true);
      updatePlot();
    }}

    function clearRuns() {{
      const select = document.getElementById("runSelect");
      Array.from(select.options).forEach(opt => opt.selected = false);
      updatePlot();
    }}

    function updateMeta(selectedRuns) {{
      const node = document.getElementById("runMeta");
      if (!selectedRuns.length) {{
        node.textContent = "Select one or more runs.";
        return;
      }}
      const lines = [];
      selectedRuns.forEach(name => {{
        const row = runMeta[name];
        if (!row) return;
        lines.push(
          name + "\\n" +
          "  mode: " + row.connection_mode + "\\n" +
          "  kind: " + row.run_kind + "\\n" +
          "  layout: " + row.technology_layout + "\\n" +
          "  selected: " + row.selected_setting_kind + "=" + row.selected_setting_value + "\\n" +
          "  cross-AFE: " + (Number.isFinite(row.mean_abs_corr_cross_afe) ? row.mean_abs_corr_cross_afe.toFixed(4) : "nan") + "\\n" +
          "  FFT floor: " + (Number.isFinite(row.median_fft_floor_dbfs) ? row.median_fft_floor_dbfs.toFixed(2) : "nan")
        );
      }});
      node.textContent = lines.join("\\n\\n");
    }}

    function updatePlot() {{
      const selectedRuns = getSelectedRuns();
      const afeFilter = document.getElementById("afeFilter").value;
      const xScale = document.getElementById("xScale").value;
      updateMeta(selectedRuns);

      const traces = [];
      selectedRuns.forEach((runName, idx) => {{
        const color = colorPalette[idx % colorPalette.length];
        traceData.forEach(item => {{
          if (item.run_name !== runName) return;
          if (afeFilter !== "all" && String(item.afe) !== afeFilter) return;
          traces.push({{
            x: item.freq_mhz,
            y: item.fft_dbfs,
            mode: "lines",
            name: item.run_name + " :: " + item.afe_label,
            line: {{
              color: color,
              width: 2,
              dash: dashMap[String(item.afe)] || "solid"
            }},
            hovertemplate:
              "<b>" + item.run_name + "</b><br>" +
              item.afe_label + "<br>" +
              "mode=" + item.connection_mode + "<br>" +
              "layout=" + item.technology_layout + "<br>" +
              "freq=%{{x:.3f}} MHz<br>" +
              "FFT=%{{y:.2f}} dBFS/bin<br>" +
              "cross-AFE=" + (Number.isFinite(item.mean_abs_corr_cross_afe) ? item.mean_abs_corr_cross_afe.toFixed(4) : "nan") + "<br>" +
              "max-pair=" + (Number.isFinite(item.max_abs_corr_value) ? item.max_abs_corr_value.toFixed(3) : "nan") +
              "<extra></extra>"
          }});
        }});
      }});

      const layout = {{
        template: "plotly_white",
        title: "Median FFT by AFE Across Selected Runs",
        xaxis: {{
          title: "Frequency [MHz]",
          type: xScale,
          autorange: true
        }},
        yaxis: {{title: "Median FFT [dBFS/bin]"}},
        legend: {{orientation: "h", yanchor: "bottom", y: 1.02, x: 0}},
        margin: {{l: 70, r: 20, t: 60, b: 70}},
        hovermode: "closest"
      }};

      Plotly.react("plot", traces, layout, {{responsive: true, displaylogo: false}});
    }}

    document.getElementById("runSelect").addEventListener("change", updatePlot);
    document.getElementById("afeFilter").addEventListener("change", updatePlot);
    document.getElementById("xScale").addEventListener("change", updatePlot);
    document.getElementById("vgainFilter").addEventListener("change", () => {{
      refreshRunOptions();
      updatePlot();
    }});
    refreshRunOptions();
    updatePlot();
  </script>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    database_rows = read_csv(Path(args.database_csv).expanduser().resolve())
    summary_rows = read_csv(Path(args.summary_csv).expanduser().resolve())
    rows = sorted(merge_rows(database_rows, summary_rows), key=lambda row: row["run_name"])

    traces: list[dict[str, Any]] = []
    for row in rows:
        traces.extend(load_fft_traces(row, args))

    out_path = Path(args.output_html).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_html(args.title, rows, traces), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
