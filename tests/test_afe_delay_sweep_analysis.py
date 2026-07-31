#!/usr/bin/env python3

from pathlib import Path
import sys
import unittest


CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from afe_delay_sweep_analysis import (  # noqa: E402
    longest_passing_window,
    summarize_afe_eye,
)


class AfeDelaySweepAnalysisTests(unittest.TestCase):
    def test_finds_longest_window_and_midpoint(self):
        window = longest_passing_window(
            [0, 4, 8, 12, 16, 20],
            [2, 0, 0, 0, 3, 0],
            [100] * 6,
        )
        self.assertEqual(window.first_tap, 4)
        self.assertEqual(window.last_tap, 12)
        self.assertEqual(window.point_count, 3)
        self.assertEqual(window.recommended_tap, 8)

    def test_accepts_configured_error_rate(self):
        window = longest_passing_window(
            [0, 1, 2],
            [2, 1, 2],
            [100, 100, 100],
            max_error_rate=0.01,
        )
        self.assertEqual((window.first_tap, window.last_tap), (1, 1))

    def test_reports_no_window(self):
        self.assertIsNone(
            longest_passing_window([0, 1], [1, 1], [100, 100])
        )

    def test_common_window_requires_every_channel(self):
        summary = summarize_afe_eye(
            [0, 4, 8, 12, 16],
            (
                [1, 0, 0, 0, 1],
                [1, 1, 0, 0, 0],
            ),
            [100] * 5,
        )
        self.assertEqual(summary.channel_windows[0].first_tap, 4)
        self.assertEqual(summary.channel_windows[1].last_tap, 16)
        self.assertEqual(summary.common_window.first_tap, 8)
        self.assertEqual(summary.common_window.last_tap, 12)

    def test_rejects_mismatched_arrays(self):
        with self.assertRaisesRegex(ValueError, "equal size"):
            longest_passing_window([0, 1], [0], [100, 100])


if __name__ == "__main__":
    unittest.main()
