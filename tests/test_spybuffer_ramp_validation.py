#!/usr/bin/env python3
"""Unit tests for the dependency-free AFE ramp validator."""

import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest


CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from spybuffer_ramp_validation import validate_ramp_data  # noqa: E402
from spybuffer_failure_artifacts import FailureArtifactWriter  # noqa: E402


class RampValidationTests(unittest.TestCase):
    def test_accepts_increment_and_wrap(self):
        result = validate_ramp_data(
            [0x3FFE, 0x3FFF, 0x0000, 0x0001],
            1,
            [7],
            4,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.transitions, 3)

    def test_reports_discontinuity_location(self):
        result = validate_ramp_data([10, 11, 900, 901], 1, [12], 4)
        self.assertFalse(result.ok)
        self.assertEqual(result.failure_count, 1)
        failure = result.failures[0]
        self.assertEqual(failure.waveform, 0)
        self.assertEqual(failure.channel, 12)
        self.assertEqual(failure.sample, 2)
        self.assertEqual(failure.previous, 11)
        self.assertEqual(failure.current, 900)
        self.assertEqual(failure.delta, 889)
        self.assertEqual(result.waveform_failure_counts, ((0, 1),))
        self.assertEqual(result.channel_failure_counts, ((12, 1),))
        self.assertEqual(result.delta_failure_counts, ((889, 1),))

    def test_understands_waveform_channel_sample_layout(self):
        data = []
        for waveform in range(2):
            for channel in range(2):
                start = 1000 * waveform + 100 * channel
                data.extend([start, start + 1, start + 2])
        data[10] += 8

        result = validate_ramp_data(data, 2, [3, 8], 3)
        self.assertEqual(result.failure_count, 2)
        self.assertEqual(result.failures[0].waveform, 1)
        self.assertEqual(result.failures[0].channel, 8)
        self.assertEqual(result.failures[0].sample, 1)
        self.assertEqual(result.waveform_failure_counts, ((1, 2),))
        self.assertEqual(result.channel_failure_counts, ((8, 2),))

    def test_rejects_wrong_flattened_size(self):
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            validate_ramp_data([0, 1, 2], 1, [0, 1], 3)

    def test_keeps_representative_failures_for_every_failing_channel(self):
        data = [10, 50, 90, 130, 1000, 1001, 1200, 1201]
        result = validate_ramp_data(
            data,
            1,
            [3, 25],
            4,
            max_reported_failures=1,
            max_failures_per_channel=2,
        )
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(
            {failure.channel for failure in result.channel_failures},
            {3, 25},
        )
        self.assertLessEqual(
            sum(failure.channel == 3 for failure in result.channel_failures),
            2,
        )
        self.assertLessEqual(
            sum(failure.channel == 25 for failure in result.channel_failures),
            2,
        )

    def test_failure_artifacts_are_lazy_and_mark_exact_transition(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base_dir = Path(temporary_directory) / "failures"
            writer = FailureArtifactWriter(
                base_dir,
                max_failure_records=10,
                max_plots=1,
                plots_per_channel=1,
                context_samples=2,
            )

            self.assertIsNone(writer.finalize({"result": "PASS"}))
            self.assertFalse(base_dir.exists())

            data = [10, 11, 900, 901]
            result = validate_ramp_data(
                data,
                1,
                [12],
                4,
                max_failures_per_channel=1,
            )
            writer.record_ramp_result(
                "normal",
                data,
                1,
                [12],
                4,
                result,
            )
            run_dir = writer.finalize({"result": "FAIL"})
            self.assertIsNotNone(run_dir)

            with (run_dir / "ramp_failures.csv").open(
                newline="", encoding="utf-8"
            ) as input_file:
                rows = list(csv.DictReader(input_file))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["waveform"], "0")
            self.assertEqual(rows[0]["channel"], "12")
            self.assertEqual(rows[0]["previous_sample"], "1")
            self.assertEqual(rows[0]["sample"], "2")
            self.assertEqual(rows[0]["expected_current"], "0x000C")
            self.assertEqual(rows[0]["current"], "0x0384")

            summary = json.loads(
                (run_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["total_ramp_failures"], 1)
            self.assertEqual(summary["ramp_failure_records_written"], 1)
            self.assertEqual(summary["plots_per_failing_channel"], 1)
            validation = summary["validation_runs_with_ramp_failures"][0]
            self.assertEqual(validation["channel_failure_counts"], {"12": 1})
            self.assertEqual(validation["delta_failure_counts"], {"889": 1})
            if not summary["plot_errors"]:
                plots = list((run_dir / "plots").glob("*.png"))
                self.assertEqual(len(plots), 1)
                self.assertEqual(summary["plots_written_by_channel"], {"12": 1})

    def test_failure_artifacts_limit_plots_independently_per_channel(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            writer = FailureArtifactWriter(
                Path(temporary_directory) / "failures",
                max_failure_records=20,
                max_plots=10,
                plots_per_channel=1,
                context_samples=2,
            )
            data = [10, 50, 90, 130, 1000, 1001, 1200, 1201]
            result = validate_ramp_data(
                data,
                1,
                [3, 25],
                4,
                max_reported_failures=20,
                max_failures_per_channel=1,
            )
            writer.record_ramp_result(
                "normal",
                data,
                1,
                [3, 25],
                4,
                result,
            )
            run_dir = writer.finalize({"result": "FAIL"})
            summary = json.loads(
                (run_dir / "summary.json").read_text(encoding="utf-8")
            )

            if not summary["plot_errors"]:
                self.assertEqual(summary["plots_written"], 2)
                self.assertEqual(
                    summary["plots_written_by_channel"],
                    {"3": 1, "25": 1},
                )


if __name__ == "__main__":
    unittest.main()
