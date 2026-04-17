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
import plotly.express as px
import plotly.graph_objects as go
from plotly.colors import qualitative


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build a self-contained Plotly HTML dashboard from no-bias noise-study CSV outputs."
    )
    ap.add_argument("--database-csv", required=True, help="Path to run_database.csv")
    ap.add_argument("--summary-csv", required=True, help="Path to crosscorr_summary.csv")
    ap.add_argument("--output-html", required=True, help="Output Plotly HTML file")
    ap.add_argument(
        "--title",
        default="No-Bias Noise Study Dashboard",
        help="Dashboard title shown in the HTML header.",
    )
    return ap.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def to_float(value: str) -> float:
    try:
        out = float(value)
    except Exception:
        return math.nan
    return out


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def metric_zscores(rows: list[dict[str, Any]], metrics: list[str]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for metric in metrics:
        values = np.asarray([float(row.get(metric, math.nan)) for row in rows], dtype=float)
        finite = np.isfinite(values)
        z = np.full(values.shape, np.nan, dtype=float)
        if finite.any():
            used = values[finite]
            mu = float(np.mean(used))
            sigma = float(np.std(used))
            if sigma > 0:
                z[finite] = (used - mu) / sigma
            else:
                z[finite] = 0.0
        out[metric] = z.tolist()
    return out


def merge_rows(
    database_rows: list[dict[str, str]],
    summary_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    by_name = {row["run_name"]: row for row in database_rows}
    merged: list[dict[str, Any]] = []
    for row in summary_rows:
        db = by_name.get(row["run_name"], {})
        payload: dict[str, Any] = dict(row)
        payload["source_root"] = db.get("source_root", "")
        payload["config_summary"] = db.get("config_summary", "")
        payload["notes"] = db.get("notes", "")
        payload["analysis_status"] = db.get("analysis_status", "")
        payload["present_on_lxplus"] = db.get("present_on_lxplus", "")
        payload["present_local"] = db.get("present_local", "")
        payload["no_bias_status"] = db.get("no_bias_status", "")
        payload["waveform_len"] = db.get("waveform_len", "")
        payload["waveforms_per_point"] = db.get("waveforms_per_point", "")
        payload["selected_setting_value_num"] = to_float(row.get("selected_setting_value", ""))
        for metric in (
            "mean_abs_corr_all",
            "mean_abs_corr_within_afe",
            "mean_abs_corr_cross_afe",
            "mean_abs_corr_with_afe3",
            "max_abs_corr_value",
            "median_fft_floor_dbfs",
            "median_fft_peak_dbfs",
            "median_fft_peak_minus_floor_db",
            "median_ac_rms_counts",
        ):
            payload[metric] = to_float(row.get(metric, ""))
        merged.append(payload)
    return merged


def build_hover_text(row: dict[str, Any]) -> str:
    lines = [
        f"<b>{html.escape(str(row['run_name']))}</b>",
        f"kind: {html.escape(str(row['run_kind']))}",
        f"mode: {html.escape(str(row['connection_mode']))}",
        f"topology: {html.escape(str(row['topology_label']))}",
        f"layout: {html.escape(str(row['technology_layout']))}",
        f"channels: {html.escape(str(row['channels']))}",
        f"selected: {html.escape(str(row['selected_setting_kind']))}={html.escape(str(row['selected_setting_value']))}",
        f"source: {html.escape(str(row['source_root']))}",
        f"max pair: {html.escape(str(row['max_abs_corr_pair']))}",
        f"outliers: {html.escape(str(row['top_outlier_channels']))}",
    ]
    return "<br>".join(lines)


def build_scatter_fig(rows: list[dict[str, Any]]) -> go.Figure:
    fig = px.scatter(
        rows,
        x="mean_abs_corr_cross_afe",
        y="median_fft_floor_dbfs",
        color="connection_mode",
        symbol="run_kind",
        size="max_abs_corr_value",
        size_max=20,
        hover_name="run_name",
        hover_data={
            "run_kind": True,
            "connection_mode": True,
            "topology_label": True,
            "technology_layout": True,
            "selected_setting_value": True,
            "mean_abs_corr_cross_afe": ":.4f",
            "median_fft_floor_dbfs": ":.2f",
            "max_abs_corr_value": ":.3f",
            "median_ac_rms_counts": ":.2f",
            "run_name": False,
        },
        title="Cross-AFE Correlation vs FFT Floor",
        labels={
            "mean_abs_corr_cross_afe": "Mean |corr| cross-AFE",
            "median_fft_floor_dbfs": "Median FFT floor [dBFS/bin]",
            "connection_mode": "Connection mode",
            "run_kind": "Run kind",
            "max_abs_corr_value": "Strongest pair |corr|",
        },
        color_discrete_sequence=qualitative.Bold,
    )
    fig.update_traces(marker=dict(line=dict(width=0.6, color="rgba(0,0,0,0.35)")))
    fig.update_layout(
        template="plotly_white",
        legend_title_text="Connection mode",
        margin=dict(l=60, r=20, t=60, b=60),
    )
    return fig


def build_localized_coupling_fig(rows: list[dict[str, Any]]) -> go.Figure:
    filtered = [
        row
        for row in rows
        if str(row.get("technology_layout", "")) != "Unknown"
        and str(row.get("connection_mode", "")) != "reference_or_unknown"
    ]
    if not filtered:
        filtered = rows
    fig = px.scatter(
        filtered,
        x="mean_abs_corr_within_afe",
        y="max_abs_corr_value",
        color="technology_layout",
        symbol="connection_mode",
        hover_name="run_name",
        hover_data={
            "run_kind": True,
            "connection_mode": True,
            "technology_layout": True,
            "max_abs_corr_pair": True,
            "top_outlier_channels": True,
            "mean_abs_corr_within_afe": ":.4f",
            "max_abs_corr_value": ":.3f",
            "mean_abs_corr_with_afe3": ":.4f",
            "run_name": False,
        },
        title="Localized Coupling View",
        labels={
            "mean_abs_corr_within_afe": "Mean |corr| within AFE",
            "max_abs_corr_value": "Strongest pair |corr|",
            "technology_layout": "Technology layout",
            "connection_mode": "Connection mode",
        },
        color_discrete_sequence=qualitative.Dark24,
    )
    fig.update_traces(marker=dict(size=11, line=dict(width=0.6, color="rgba(0,0,0,0.3)")))
    fig.update_layout(
        template="plotly_white",
        legend_title_text="Technology layout",
        margin=dict(l=60, r=20, t=60, b=60),
    )
    return fig


def build_ranked_bar_fig(rows: list[dict[str, Any]]) -> go.Figure:
    ordered = sorted(rows, key=lambda row: (row["mean_abs_corr_cross_afe"], row["max_abs_corr_value"]), reverse=True)
    labels = [row["run_name"] for row in ordered]
    fig = go.Figure()
    fig.add_bar(
        x=[row["mean_abs_corr_cross_afe"] for row in ordered],
        y=labels,
        orientation="h",
        name="Cross-AFE mean |corr|",
        marker_color="#1f77b4",
        hovertext=[build_hover_text(row) for row in ordered],
        hoverinfo="text",
    )
    fig.add_bar(
        x=[row["max_abs_corr_value"] for row in ordered],
        y=labels,
        orientation="h",
        name="Strongest pair |corr|",
        marker_color="#d62728",
        opacity=0.72,
        hovertext=[build_hover_text(row) for row in ordered],
        hoverinfo="text",
    )
    fig.update_layout(
        barmode="group",
        template="plotly_white",
        title="Runs Ranked by Crosstalk-Like Metrics",
        xaxis_title="Metric value",
        yaxis_title="Run",
        height=max(900, 26 * len(ordered)),
        margin=dict(l=260, r=20, t=60, b=60),
    )
    fig.update_yaxes(autorange="reversed")
    return fig


def build_heatmap_fig(rows: list[dict[str, Any]]) -> go.Figure:
    metrics = [
        "mean_abs_corr_all",
        "mean_abs_corr_cross_afe",
        "mean_abs_corr_with_afe3",
        "max_abs_corr_value",
        "median_fft_floor_dbfs",
        "median_fft_peak_minus_floor_db",
        "median_ac_rms_counts",
    ]
    zscores = metric_zscores(rows, metrics)
    ordered = sorted(rows, key=lambda row: row["run_name"])
    z = np.asarray([[zscores[m][rows.index(row)] for m in metrics] for row in ordered], dtype=float)
    custom = np.empty(z.shape, dtype=object)
    for i, row in enumerate(ordered):
        for j, metric in enumerate(metrics):
            custom[i, j] = f"{row[metric]:.4f}" if math.isfinite(float(row[metric])) else "nan"

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=metrics,
            y=[row["run_name"] for row in ordered],
            colorscale="RdBu_r",
            zmid=0.0,
            colorbar_title="z-score",
            customdata=custom,
            hovertemplate="run=%{y}<br>metric=%{x}<br>z=%{z:.2f}<br>raw=%{customdata}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_white",
        title="Standardized Metric Heatmap Across Runs",
        height=max(900, 24 * len(ordered)),
        margin=dict(l=260, r=20, t=60, b=60),
    )
    return fig


def build_table_fig(rows: list[dict[str, Any]]) -> go.Figure:
    ordered = sorted(rows, key=lambda row: row["mean_abs_corr_cross_afe"], reverse=True)[:15]
    fig = go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=[
                        "Run",
                        "Kind",
                        "Mode",
                        "Cross-AFE",
                        "Max pair",
                        "Max |corr|",
                        "FFT floor",
                        "Peak-floor",
                    ],
                    fill_color="#23374d",
                    font=dict(color="white", size=12),
                    align="left",
                ),
                cells=dict(
                    values=[
                        [row["run_name"] for row in ordered],
                        [row["run_kind"] for row in ordered],
                        [row["connection_mode"] for row in ordered],
                        [f"{row['mean_abs_corr_cross_afe']:.4f}" for row in ordered],
                        [row["max_abs_corr_pair"] for row in ordered],
                        [f"{row['max_abs_corr_value']:.3f}" for row in ordered],
                        [f"{row['median_fft_floor_dbfs']:.2f}" for row in ordered],
                        [f"{row['median_fft_peak_minus_floor_db']:.2f}" for row in ordered],
                    ],
                    fill_color="#f8fafc",
                    align="left",
                    font=dict(size=11),
                    height=24,
                ),
            )
        ]
    )
    fig.update_layout(
        template="plotly_white",
        title="Top 15 Runs by Cross-AFE Mean Correlation",
        margin=dict(l=20, r=20, t=60, b=20),
        height=500,
    )
    return fig


def fig_html(fig: go.Figure, include_js: bool) -> str:
    return fig.to_html(full_html=False, include_plotlyjs="inline" if include_js else False)


def build_html(title: str, rows: list[dict[str, Any]]) -> str:
    scatter = build_scatter_fig(rows)
    local = build_localized_coupling_fig(rows)
    ranked = build_ranked_bar_fig(rows)
    heatmap = build_heatmap_fig(rows)
    table = build_table_fig(rows)

    summary = {
        "runs": len(rows),
        "run_kinds": sorted({str(row["run_kind"]) for row in rows}),
        "connection_modes": sorted({str(row["connection_mode"]) for row in rows}),
    }

    sections = [
        fig_html(scatter, include_js=True),
        fig_html(local, include_js=False),
        fig_html(ranked, include_js=False),
        fig_html(heatmap, include_js=False),
        fig_html(table, include_js=False),
    ]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      margin: 0;
      background: #f3f5f7;
      color: #1f2933;
    }}
    .wrap {{
      max-width: 1680px;
      margin: 0 auto;
      padding: 24px 24px 48px;
    }}
    h1, h2 {{
      margin: 0 0 12px;
      font-weight: 700;
    }}
    .meta {{
      margin: 0 0 20px;
      padding: 14px 16px;
      background: white;
      border: 1px solid #d9e2ec;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 18px;
    }}
    .card {{
      background: white;
      border: 1px solid #d9e2ec;
      padding: 10px 10px 2px;
    }}
    code {{
      background: #eef2f6;
      padding: 1px 4px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(title)}</h1>
    <div class="meta">
      <div>Analyzed runs: <code>{summary['runs']}</code></div>
      <div>Run kinds: <code>{html.escape(', '.join(summary['run_kinds']))}</code></div>
      <div>Connection modes: <code>{html.escape(', '.join(summary['connection_modes']))}</code></div>
      <div>Hover a point or bar for topology, channel map, strongest pair, and outlier-channel context.</div>
    </div>
    <div class="grid">
      <div class="card">{sections[0]}</div>
      <div class="card">{sections[1]}</div>
      <div class="card">{sections[2]}</div>
      <div class="card">{sections[3]}</div>
      <div class="card">{sections[4]}</div>
    </div>
  </div>
</body>
</html>
"""


def main() -> int:
    args = parse_args()
    database_rows = read_csv(Path(args.database_csv).expanduser().resolve())
    summary_rows = read_csv(Path(args.summary_csv).expanduser().resolve())
    rows = merge_rows(database_rows, summary_rows)
    rows = [row for row in rows if row.get("analysis_status") == "analyzed"]
    if not rows:
        raise SystemExit("No analyzed rows found in the merged input.")

    out_path = Path(args.output_html).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_html(args.title, rows), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
