"""Pure AFE5808A test-pattern validation and channel diagnosis helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence


ADC_BITS = 14
ADC_MASK = (1 << ADC_BITS) - 1


@dataclass(frozen=True)
class PatternDefinition:
    name: str
    description: str
    mode: int
    behavior: str
    category: str
    expected_code: int | None = None
    custom_value: int | None = None
    source_bit: int | None = None


@dataclass(frozen=True)
class PatternFailure:
    waveform: int
    channel: int
    sample: int
    kind: str
    previous: int | None
    current: int
    expected: int | None


@dataclass(frozen=True)
class ChannelPatternResult:
    channel: int
    checks: int
    failure_count: int
    value_failures: int
    transition_failures: int
    failing_bits: tuple[int, ...]
    false_positive_bits: tuple[tuple[int, int], ...]
    false_negative_bits: tuple[tuple[int, int], ...]
    dominant_code: int
    dominant_count: int
    unique_code_count: int
    observed_code_counts: tuple[tuple[int, int], ...]
    examples: tuple[PatternFailure, ...]

    @property
    def ok(self) -> bool:
        return self.failure_count == 0


@dataclass(frozen=True)
class PatternValidationResult:
    pattern: PatternDefinition
    waveform_count: int
    samples_per_waveform: int
    channels: tuple[int, ...]
    checks: int
    failure_count: int
    channel_results: tuple[ChannelPatternResult, ...]

    @property
    def ok(self) -> bool:
        return self.failure_count == 0


@dataclass(frozen=True)
class ChannelDiagnosis:
    channel: int
    status: str
    classification: str
    custom_failures: int
    builtin_failures: int
    temporal_failures: int
    failing_bits: tuple[int, ...]
    bit_response: tuple[str, ...]
    interpretation: str

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


def build_pattern_suite() -> tuple[PatternDefinition, ...]:
    """Return the diagnostic sequence in the order applied to the AFE."""

    patterns = [
        PatternDefinition(
            name="zeros",
            description="built-in all-zero word",
            mode=6,
            behavior="constant",
            category="builtin",
            expected_code=0x0000,
        ),
        PatternDefinition(
            name="ones",
            description="built-in all-one word",
            mode=4,
            behavior="constant",
            category="builtin",
            expected_code=ADC_MASK,
        ),
        PatternDefinition(
            name="deskew",
            description="built-in alternating-bit deskew word",
            mode=2,
            behavior="constant",
            category="builtin",
            expected_code=0x1555,
        ),
        PatternDefinition(
            name="sync-word",
            description="built-in 11111110000000 synchronization word",
            mode=1,
            behavior="constant",
            category="builtin",
            expected_code=0x3F80,
        ),
    ]

    for bit in range(ADC_BITS):
        value = 1 << bit
        patterns.append(
            PatternDefinition(
                name=f"walking-one-d{bit:02d}",
                description=f"custom word with only ADC bit D{bit} high",
                mode=3,
                behavior="constant",
                category="custom-one",
                expected_code=value,
                custom_value=value,
                source_bit=bit,
            )
        )

    for bit in range(ADC_BITS):
        value = ADC_MASK ^ (1 << bit)
        patterns.append(
            PatternDefinition(
                name=f"walking-zero-d{bit:02d}",
                description=f"custom word with only ADC bit D{bit} low",
                mode=3,
                behavior="constant",
                category="custom-zero",
                expected_code=value,
                custom_value=value,
                source_bit=bit,
            )
        )

    patterns.append(
        PatternDefinition(
            name="toggle",
            description="built-in alternating all-zero/all-one words",
            mode=5,
            behavior="toggle",
            category="temporal",
        )
    )
    return tuple(patterns)


def _top_counts(counter: Counter[int], limit: int) -> tuple[tuple[int, int], ...]:
    return tuple(sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:limit])


def validate_pattern_data(
    pattern: PatternDefinition,
    data: Sequence[int],
    waveform_count: int,
    channels: Sequence[int],
    samples_per_waveform: int,
    *,
    max_examples_per_channel: int = 4,
    max_observed_codes: int = 16,
) -> PatternValidationResult:
    """Validate flattened ``[waveform][channel][sample]`` spybuffer data."""

    if pattern.behavior not in ("constant", "toggle"):
        raise ValueError(f"Unsupported pattern behavior: {pattern.behavior}")
    if pattern.behavior == "constant" and pattern.expected_code is None:
        raise ValueError("A constant pattern requires expected_code")
    if waveform_count < 1:
        raise ValueError("waveform_count must be greater than zero")
    if not channels:
        raise ValueError("channels must not be empty")
    if samples_per_waveform < 2:
        raise ValueError("samples_per_waveform must be at least two")
    if max_examples_per_channel < 0:
        raise ValueError("max_examples_per_channel cannot be negative")
    if max_observed_codes < 1:
        raise ValueError("max_observed_codes must be greater than zero")

    expected_words = waveform_count * len(channels) * samples_per_waveform
    if len(data) != expected_words:
        raise ValueError(
            f"Pattern data size mismatch: {len(data)} != {expected_words}"
        )

    channel_results: list[ChannelPatternResult] = []
    total_checks = 0
    total_failures = 0

    for channel_index, channel in enumerate(channels):
        observed: Counter[int] = Counter()
        false_positive: Counter[int] = Counter()
        false_negative: Counter[int] = Counter()
        failing_bits: set[int] = set()
        examples: list[PatternFailure] = []
        value_failures = 0
        transition_failures = 0

        for waveform in range(waveform_count):
            base = (
                (waveform * len(channels) + channel_index)
                * samples_per_waveform
            )
            previous: int | None = None
            for sample in range(samples_per_waveform):
                current = int(data[base + sample]) & ADC_MASK
                observed[current] += 1

                if pattern.behavior == "constant":
                    expected = int(pattern.expected_code) & ADC_MASK
                    if current != expected:
                        value_failures += 1
                        difference = current ^ expected
                        for bit in range(ADC_BITS):
                            mask = 1 << bit
                            if not difference & mask:
                                continue
                            failing_bits.add(bit)
                            if current & mask:
                                false_positive[bit] += 1
                            else:
                                false_negative[bit] += 1
                        if len(examples) < max_examples_per_channel:
                            examples.append(
                                PatternFailure(
                                    waveform=waveform,
                                    channel=int(channel),
                                    sample=sample,
                                    kind="wrong-code",
                                    previous=previous,
                                    current=current,
                                    expected=expected,
                                )
                            )
                else:
                    if current not in (0x0000, ADC_MASK):
                        value_failures += 1
                        if len(examples) < max_examples_per_channel:
                            examples.append(
                                PatternFailure(
                                    waveform=waveform,
                                    channel=int(channel),
                                    sample=sample,
                                    kind="hybrid-toggle-code",
                                    previous=previous,
                                    current=current,
                                    expected=None,
                                )
                            )
                    if sample > 0 and current == previous:
                        transition_failures += 1
                        if len(examples) < max_examples_per_channel:
                            examples.append(
                                PatternFailure(
                                    waveform=waveform,
                                    channel=int(channel),
                                    sample=sample,
                                    kind="toggle-did-not-change",
                                    previous=previous,
                                    current=current,
                                    expected=(ADC_MASK ^ current),
                                )
                            )
                previous = current

        sample_checks = waveform_count * samples_per_waveform
        transition_checks = (
            waveform_count * (samples_per_waveform - 1)
            if pattern.behavior == "toggle"
            else 0
        )
        checks = sample_checks + transition_checks
        failures = value_failures + transition_failures
        dominant_code, dominant_count = _top_counts(observed, 1)[0]
        channel_result = ChannelPatternResult(
            channel=int(channel),
            checks=checks,
            failure_count=failures,
            value_failures=value_failures,
            transition_failures=transition_failures,
            failing_bits=tuple(sorted(failing_bits)),
            false_positive_bits=tuple(sorted(false_positive.items())),
            false_negative_bits=tuple(sorted(false_negative.items())),
            dominant_code=dominant_code,
            dominant_count=dominant_count,
            unique_code_count=len(observed),
            observed_code_counts=_top_counts(observed, max_observed_codes),
            examples=tuple(examples),
        )
        channel_results.append(channel_result)
        total_checks += checks
        total_failures += failures

    return PatternValidationResult(
        pattern=pattern,
        waveform_count=waveform_count,
        samples_per_waveform=samples_per_waveform,
        channels=tuple(int(channel) for channel in channels),
        checks=total_checks,
        failure_count=total_failures,
        channel_results=tuple(channel_results),
    )


def _format_bit_response(
    source_bit: int,
    channel_result: ChannelPatternResult,
) -> str | None:
    expected = 1 << source_bit
    if channel_result.ok and channel_result.dominant_code == expected:
        return None
    observed = channel_result.dominant_code
    stability = (
        "stable"
        if channel_result.dominant_count
        == channel_result.checks
        else f"dominant {channel_result.dominant_count}/{channel_result.checks}"
    )
    if observed == 0:
        response = "missing"
    else:
        output_bits = [bit for bit in range(ADC_BITS) if observed & (1 << bit)]
        response = "D" + "+D".join(str(bit) for bit in output_bits)
    return f"D{source_bit}->{response} ({stability})"


def diagnose_channels(
    results: Sequence[PatternValidationResult],
    channels: Sequence[int],
) -> tuple[ChannelDiagnosis, ...]:
    """Classify static bit-path and temporal word-boundary failures."""

    by_channel: dict[int, list[tuple[PatternDefinition, ChannelPatternResult]]] = {
        int(channel): [] for channel in channels
    }
    for result in results:
        result_by_channel = {
            channel_result.channel: channel_result
            for channel_result in result.channel_results
        }
        for channel in by_channel:
            if channel not in result_by_channel:
                raise ValueError(
                    f"Pattern {result.pattern.name} has no result for ch{channel}"
                )
            by_channel[channel].append(
                (result.pattern, result_by_channel[channel])
            )

    diagnoses: list[ChannelDiagnosis] = []
    for channel in channels:
        custom_failures = 0
        builtin_failures = 0
        temporal_failures = 0
        failing_bits: set[int] = set()
        bit_response: list[str] = []

        for pattern, channel_result in by_channel[int(channel)]:
            if pattern.category.startswith("custom"):
                custom_failures += channel_result.failure_count
            elif pattern.category == "builtin":
                builtin_failures += channel_result.failure_count
            elif pattern.category == "temporal":
                temporal_failures += channel_result.failure_count
            failing_bits.update(channel_result.failing_bits)

            if pattern.category == "custom-one" and pattern.source_bit is not None:
                response = _format_bit_response(pattern.source_bit, channel_result)
                if response is not None:
                    bit_response.append(response)

        if custom_failures:
            if temporal_failures:
                classification = "STATIC_AND_TEMPORAL_FAILURE"
                interpretation = (
                    "The custom walking patterns do not preserve the 14-bit "
                    "word and toggle also fails; investigate bit placement, "
                    "bitslip/serialization, and word-boundary timing."
                )
            else:
                classification = "STATIC_BIT_PATH_FAILURE"
                interpretation = (
                    "A constant custom word is received incorrectly; this is "
                    "a static bit-placement/deserialization fault, not merely "
                    "a transition between ADC words."
                )
        elif temporal_failures:
            classification = "TEMPORAL_WORD_BOUNDARY_FAILURE"
            interpretation = (
                "All custom bit positions are correct when words are static, "
                "but alternating words are corrupted; this is consistent with "
                "mixing or tearing across an ADC word boundary."
            )
        elif builtin_failures:
            classification = "BUILTIN_PATTERN_MISMATCH"
            interpretation = (
                "Custom bit mapping is correct, but a built-in fixed pattern "
                "does not match its documented code; verify AFE mode, output "
                "format, and pattern configuration."
            )
        else:
            classification = "PASS"
            interpretation = (
                "Static bit placement and alternating-word timing both match "
                "the expected 14-bit AFE output."
            )

        status = "PASS" if classification == "PASS" else "FAIL"
        diagnoses.append(
            ChannelDiagnosis(
                channel=int(channel),
                status=status,
                classification=classification,
                custom_failures=custom_failures,
                builtin_failures=builtin_failures,
                temporal_failures=temporal_failures,
                failing_bits=tuple(sorted(failing_bits)),
                bit_response=tuple(bit_response),
                interpretation=interpretation,
            )
        )
    return tuple(diagnoses)
