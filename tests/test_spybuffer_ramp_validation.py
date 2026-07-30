#!/usr/bin/env python3
"""Unit tests for the dependency-free AFE ramp validator."""

from pathlib import Path
import sys
import unittest


CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from spybuffer_ramp_validation import validate_ramp_data  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
