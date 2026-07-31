"""Failure-only diagnostic artifacts for the spybuffer ramp campaign."""

from __future__ import annotations

import csv
from collections import Counter
import json
from pathlib import Path
import re
import time
import uuid
from typing import Sequence

from spybuffer_ramp_validation import RAMP_MASK, RampValidationResult


class FailureArtifactWriter:
    """Create a timestamped artifact directory lazily on the first failure."""

    def __init__(
        self,
        base_dir: Path,
        *,
        max_failure_records: int,
        max_plots: int,
        plots_per_channel: int,
        context_samples: int,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.max_failure_records = max(0, int(max_failure_records))
        self.max_plots = max(0, int(max_plots))
        self.plots_per_channel = max(0, int(plots_per_channel))
        self.context_samples = max(1, int(context_samples))

        self.run_dir: Path | None = None
        self._ramp_csv = None
        self._ramp_writer = None
        self._timestamp_csv = None
        self._timestamp_writer = None
        self._plots_written = 0
        self._channel_plot_counts: Counter[int] = Counter()
        self._ramp_records_written = 0
        self._timestamp_records_written = 0
        self._total_ramp_failures = 0
        self._total_timestamp_failures = 0
        self._validation_runs: list[dict[str, object]] = []
        self._errors: list[str] = []
        self._plot_errors: list[str] = []
        self._plotting_disabled = False

    def _ensure_run_dir(self) -> Path:
        if self.run_dir is not None:
            return self.run_dir

        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.run_dir = self.base_dir / f"{timestamp}_{uuid.uuid4().hex[:8]}"
        self.run_dir.mkdir(parents=True, exist_ok=False)
        (self.run_dir / "plots").mkdir()
        return self.run_dir

    def _ensure_ramp_csv(self):
        if self._ramp_writer is not None:
            return self._ramp_writer
        run_dir = self._ensure_run_dir()
        self._ramp_csv = (run_dir / "ramp_failures.csv").open(
            "w", newline="", encoding="utf-8"
        )
        self._ramp_writer = csv.DictWriter(
            self._ramp_csv,
            fieldnames=(
                "api",
                "waveform",
                "channel",
                "sample",
                "previous_sample",
                "previous",
                "current",
                "expected_current",
                "delta_mod_14bit",
                "delta_signed",
            ),
        )
        self._ramp_writer.writeheader()
        return self._ramp_writer

    def _ensure_timestamp_csv(self):
        if self._timestamp_writer is not None:
            return self._timestamp_writer
        run_dir = self._ensure_run_dir()
        self._timestamp_csv = (run_dir / "timestamp_failures.csv").open(
            "w", newline="", encoding="utf-8"
        )
        self._timestamp_writer = csv.DictWriter(
            self._timestamp_csv,
            fieldnames=(
                "api",
                "waveform",
                "kind",
                "previous",
                "current",
                "delta_mod_64bit",
            ),
        )
        self._timestamp_writer.writeheader()
        return self._timestamp_writer

    @staticmethod
    def _waveform_values(
        data: Sequence[int],
        waveform: int,
        channel_index: int,
        channel_count: int,
        samples: int,
    ) -> list[int]:
        base = (waveform * channel_count + channel_index) * samples
        return [int(value) & RAMP_MASK for value in data[base : base + samples]]

    def _write_failure_plot(
        self,
        api_label: str,
        waveform: int,
        channel: int,
        sample: int,
        values: Sequence[int],
        previous: int,
        current: int,
        delta: int,
    ) -> bool:
        if self._plotting_disabled or self._plots_written >= self.max_plots:
            return False

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            expected = (previous + 1) & RAMP_MASK
            signed_delta = delta - (1 << 14) if delta > (1 << 13) else delta
            first = max(0, sample - self.context_samples)
            last = min(len(values), sample + self.context_samples + 1)
            x_values = list(range(len(values)))

            figure, (full_axis, detail_axis) = plt.subplots(
                2,
                1,
                figsize=(13, 8),
                gridspec_kw={"height_ratios": [1.25, 1]},
            )
            full_axis.plot(x_values, values, linewidth=0.8, color="tab:blue")
            full_axis.axvspan(sample - 1, sample, color="red", alpha=0.22)
            full_axis.scatter(
                [sample - 1, sample],
                [previous, current],
                color="red",
                s=32,
                zorder=4,
                label="failing transition",
            )
            full_axis.set_title(
                f"{api_label}: waveform {waveform}, channel {channel}, "
                f"failure at sample {sample}"
            )
            full_axis.set_xlabel("Sample")
            full_axis.set_ylabel("ADC ramp code (14 bit)")
            full_axis.grid(True, alpha=0.25)
            full_axis.legend(loc="best")

            detail_x = list(range(first, last))
            detail_axis.plot(
                detail_x,
                values[first:last],
                marker=".",
                linewidth=1.0,
                color="tab:blue",
            )
            detail_axis.axvspan(sample - 1, sample, color="red", alpha=0.22)
            detail_axis.scatter(
                [sample - 1, sample],
                [previous, current],
                color="red",
                s=55,
                zorder=5,
            )
            detail_axis.scatter(
                [sample],
                [expected],
                marker="x",
                color="green",
                s=90,
                linewidth=2,
                zorder=6,
                label=f"expected 0x{expected:04X}",
            )
            detail_axis.annotate(
                f"actual 0x{current:04X}\n"
                f"delta={delta} ({signed_delta:+d})",
                xy=(sample, current),
                xytext=(10, 20),
                textcoords="offset points",
                arrowprops={"arrowstyle": "->", "color": "red"},
            )
            detail_axis.set_xlim(first, max(first + 1, last - 1))
            detail_axis.set_xlabel("Sample")
            detail_axis.set_ylabel("ADC ramp code (14 bit)")
            detail_axis.grid(True, alpha=0.25)
            detail_axis.legend(loc="best")

            figure.tight_layout()
            safe_api = re.sub(r"[^A-Za-z0-9_.-]+", "_", api_label)
            filename = (
                f"{safe_api}_wf{waveform:06d}_ch{channel:02d}_"
                f"sample{sample:04d}.png"
            )
            figure.savefig(self._ensure_run_dir() / "plots" / filename, dpi=160)
            plt.close(figure)
            self._plots_written += 1
            return True
        except Exception as error:
            self._plot_errors.append(
                f"{api_label} waveform={waveform} channel={channel} "
                f"sample={sample}: {error}"
            )
            self._plotting_disabled = True
            return False

    def record_ramp_result(
        self,
        api_label: str,
        data: Sequence[int],
        waveform_count: int,
        channels: Sequence[int],
        samples: int,
        result: RampValidationResult,
        *,
        waveform_offset: int = 0,
    ) -> None:
        if result.failure_count == 0:
            return

        self._ensure_run_dir()
        self._total_ramp_failures += result.failure_count
        self._validation_runs.append(
            {
                "api": api_label,
                "waveform_offset": waveform_offset,
                "waveforms": waveform_count,
                "channels": list(channels),
                "samples": samples,
                "transitions": result.transitions,
                "ramp_failures": result.failure_count,
                "waveform_failure_counts": dict(
                    result.waveform_failure_counts
                ),
                "channel_failure_counts": dict(
                    result.channel_failure_counts
                ),
                "delta_failure_counts": dict(result.delta_failure_counts),
            }
        )

        channel_indices = {
            int(channel): index for index, channel in enumerate(channels)
        }
        for failure in result.failures:
            if self._ramp_records_written >= self.max_failure_records:
                break

            global_waveform = waveform_offset + failure.waveform
            expected = (failure.previous + 1) & RAMP_MASK
            signed_delta = (
                failure.delta - (1 << 14)
                if failure.delta > (1 << 13)
                else failure.delta
            )
            writer = self._ensure_ramp_csv()
            writer.writerow(
                {
                    "api": api_label,
                    "waveform": global_waveform,
                    "channel": failure.channel,
                    "sample": failure.sample,
                    "previous_sample": failure.sample - 1,
                    "previous": f"0x{failure.previous:04X}",
                    "current": f"0x{failure.current:04X}",
                    "expected_current": f"0x{expected:04X}",
                    "delta_mod_14bit": failure.delta,
                    "delta_signed": signed_delta,
                }
            )
            self._ramp_records_written += 1

        if self._ramp_csv is not None:
            self._ramp_csv.flush()

        for failure in result.channel_failures:
            channel = int(failure.channel)
            if self._channel_plot_counts[channel] >= self.plots_per_channel:
                continue
            if self._plots_written >= self.max_plots:
                break

            values = self._waveform_values(
                data,
                failure.waveform,
                channel_indices[channel],
                len(channels),
                samples,
            )
            if self._write_failure_plot(
                api_label,
                waveform_offset + failure.waveform,
                channel,
                failure.sample,
                values,
                failure.previous,
                failure.current,
                failure.delta,
            ):
                self._channel_plot_counts[channel] += 1

    def record_timestamp_failures(
        self,
        api_label: str,
        timestamps: Sequence[int],
        failures: Sequence[object],
    ) -> None:
        if not failures:
            return

        self._ensure_run_dir()
        self._total_timestamp_failures += len(failures)
        writer = self._ensure_timestamp_csv()
        for failure in failures:
            writer.writerow(
                {
                    "api": api_label,
                    "waveform": failure.waveform,
                    "kind": failure.kind,
                    "previous": f"0x{failure.previous:016X}",
                    "current": f"0x{failure.current:016X}",
                    "delta_mod_64bit": failure.delta,
                }
            )
            self._timestamp_records_written += 1
        self._timestamp_csv.flush()

        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            if len(timestamps) > 1:
                deltas = [
                    (int(timestamps[index]) - int(timestamps[index - 1]))
                    & ((1 << 64) - 1)
                    for index in range(1, len(timestamps))
                ]
                figure, axis = plt.subplots(figsize=(13, 5))
                axis.plot(
                    range(1, len(timestamps)),
                    deltas,
                    marker=".",
                    linewidth=0.8,
                )
                for failure in failures:
                    axis.axvline(failure.waveform, color="red", alpha=0.5)
                    axis.scatter(
                        [failure.waveform],
                        [failure.delta],
                        color="red",
                        zorder=4,
                    )
                axis.set_title(f"{api_label}: timestamp deltas")
                axis.set_xlabel("Waveform")
                axis.set_ylabel("Timestamp delta (modulo 64 bit)")
                axis.grid(True, alpha=0.25)
                figure.tight_layout()
                safe_api = re.sub(r"[^A-Za-z0-9_.-]+", "_", api_label)
                figure.savefig(
                    self._ensure_run_dir()
                    / "plots"
                    / f"{safe_api}_timestamp_failures.png",
                    dpi=160,
                )
                plt.close(figure)
        except Exception as error:
            self._plot_errors.append(f"{api_label} timestamp plot: {error}")

    def record_error(self, message: str) -> None:
        self._ensure_run_dir()
        self._errors.append(str(message))

    def finalize(self, summary: dict[str, object]) -> Path | None:
        if self.run_dir is None:
            return None

        if self._ramp_csv is not None:
            self._ramp_csv.close()
            self._ramp_csv = None
        if self._timestamp_csv is not None:
            self._timestamp_csv.close()
            self._timestamp_csv = None

        manifest = dict(summary)
        manifest.update(
            {
                "total_ramp_failures": self._total_ramp_failures,
                "ramp_failure_records_written": self._ramp_records_written,
                "ramp_failure_records_omitted": max(
                    0, self._total_ramp_failures - self._ramp_records_written
                ),
                "total_timestamp_failures": self._total_timestamp_failures,
                "timestamp_failure_records_written": (
                    self._timestamp_records_written
                ),
                "plots_written": self._plots_written,
                "max_plots": self.max_plots,
                "plots_per_failing_channel": self.plots_per_channel,
                "plots_written_by_channel": dict(
                    sorted(self._channel_plot_counts.items())
                ),
                "validation_runs_with_ramp_failures": self._validation_runs,
                "errors": self._errors,
                "plot_errors": self._plot_errors,
            }
        )
        with (self.run_dir / "summary.json").open("w", encoding="utf-8") as output:
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write("\n")
        return self.run_dir
