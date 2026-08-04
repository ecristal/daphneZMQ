#!/usr/bin/env python3
"""Unit tests for AFE fixed-pattern validation and diagnosis."""

from pathlib import Path
import sys
import unittest


CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from afe_pattern_validation import (  # noqa: E402
    ADC_MASK,
    PatternDefinition,
    build_pattern_suite,
    diagnose_channels,
    validate_pattern_data,
)


class AfePatternValidationTests(unittest.TestCase):
    def test_suite_covers_documented_fixed_walking_and_toggle_patterns(self):
        patterns = build_pattern_suite()
        self.assertEqual(len(patterns), 33)
        self.assertEqual(
            [(pattern.name, pattern.mode, pattern.expected_code) for pattern in patterns[:4]],
            [
                ("zeros", 6, 0x0000),
                ("ones", 4, 0x3FFF),
                ("deskew", 2, 0x1555),
                ("sync-word", 1, 0x3F80),
            ],
        )
        walking_one = [
            pattern for pattern in patterns if pattern.category == "custom-one"
        ]
        walking_zero = [
            pattern for pattern in patterns if pattern.category == "custom-zero"
        ]
        self.assertEqual(
            [pattern.expected_code for pattern in walking_one],
            [1 << bit for bit in range(14)],
        )
        self.assertEqual(
            [pattern.expected_code for pattern in walking_zero],
            [ADC_MASK ^ (1 << bit) for bit in range(14)],
        )
        self.assertEqual(patterns[-1].name, "toggle")
        self.assertEqual(patterns[-1].mode, 5)

    def test_constant_pattern_accepts_exact_multichannel_layout(self):
        pattern = PatternDefinition(
            "custom",
            "test",
            3,
            "constant",
            "custom-one",
            expected_code=0x0123,
        )
        result = validate_pattern_data(
            pattern,
            [0x0123] * (2 * 3 * 4),
            2,
            [3, 9, 25],
            4,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.checks, 24)
        self.assertTrue(all(channel.ok for channel in result.channel_results))

    def test_constant_pattern_identifies_missing_bit(self):
        pattern = PatternDefinition(
            "walking-one-d01",
            "test D1",
            3,
            "constant",
            "custom-one",
            expected_code=0x0002,
            custom_value=0x0002,
            source_bit=1,
        )
        result = validate_pattern_data(pattern, [0, 0, 0, 0], 1, [3], 4)
        channel = result.channel_results[0]
        self.assertFalse(channel.ok)
        self.assertEqual(channel.failure_count, 4)
        self.assertEqual(channel.failing_bits, (1,))
        self.assertEqual(channel.false_negative_bits, ((1, 4),))
        self.assertEqual(channel.false_positive_bits, ())
        self.assertEqual(channel.dominant_code, 0)

        diagnosis = diagnose_channels([result], [3])[0]
        self.assertEqual(diagnosis.classification, "STATIC_BIT_PATH_FAILURE")
        self.assertEqual(diagnosis.failing_bits, (1,))
        self.assertEqual(diagnosis.bit_response, ("D1->missing (stable)",))

    def test_toggle_accepts_either_starting_polarity(self):
        toggle = build_pattern_suite()[-1]
        result = validate_pattern_data(
            toggle,
            [0, ADC_MASK, 0, ADC_MASK, ADC_MASK, 0, ADC_MASK, 0],
            2,
            [25],
            4,
        )
        self.assertTrue(result.ok)
        channel = result.channel_results[0]
        self.assertEqual(channel.value_failures, 0)
        self.assertEqual(channel.transition_failures, 0)
        self.assertEqual(channel.checks, 14)

    def test_toggle_separates_hybrid_codes_from_missing_transitions(self):
        toggle = build_pattern_suite()[-1]
        result = validate_pattern_data(
            toggle,
            [0, ADC_MASK, ADC_MASK, 0x0100],
            1,
            [25],
            4,
        )
        channel = result.channel_results[0]
        self.assertEqual(channel.value_failures, 1)
        self.assertEqual(channel.transition_failures, 1)
        self.assertEqual(channel.failure_count, 2)
        self.assertEqual(
            {example.kind for example in channel.examples},
            {"hybrid-toggle-code", "toggle-did-not-change"},
        )

    def test_static_pass_and_toggle_fail_classifies_temporal_boundary(self):
        custom = PatternDefinition(
            "walking-one-d00",
            "test D0",
            3,
            "constant",
            "custom-one",
            expected_code=1,
            custom_value=1,
            source_bit=0,
        )
        static_result = validate_pattern_data(custom, [1, 1, 1, 1], 1, [25], 4)
        toggle_result = validate_pattern_data(
            build_pattern_suite()[-1],
            [0, ADC_MASK, ADC_MASK, 0],
            1,
            [25],
            4,
        )
        diagnosis = diagnose_channels([static_result, toggle_result], [25])[0]
        self.assertEqual(
            diagnosis.classification,
            "TEMPORAL_WORD_BOUNDARY_FAILURE",
        )
        self.assertEqual(diagnosis.custom_failures, 0)
        self.assertGreater(diagnosis.temporal_failures, 0)

    def test_rejects_wrong_flattened_size(self):
        pattern = build_pattern_suite()[0]
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            validate_pattern_data(pattern, [0, 0, 0], 1, [0, 1], 2)


if __name__ == "__main__":
    unittest.main()
