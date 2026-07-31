"""Pure helpers for validating AFE5808A ramp waveforms."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence


RAMP_MODULUS = 1 << 14
RAMP_MASK = RAMP_MODULUS - 1


@dataclass(frozen=True)
class RampFailure:
    waveform: int
    channel: int
    sample: int
    previous: int
    current: int
    delta: int


@dataclass(frozen=True)
class RampValidationResult:
    transitions: int
    failure_count: int
    failures: tuple[RampFailure, ...]
    channel_failures: tuple[RampFailure, ...]
    waveform_failure_counts: tuple[tuple[int, int], ...]
    channel_failure_counts: tuple[tuple[int, int], ...]
    delta_failure_counts: tuple[tuple[int, int], ...]

    @property
    def ok(self) -> bool:
        return self.failure_count == 0


def validate_ramp_data(
    data: Sequence[int],
    waveform_count: int,
    channels: Sequence[int],
    samples_per_waveform: int,
    *,
    max_reported_failures: int = 20,
    max_failures_per_channel: int = 0,
) -> RampValidationResult:
    """Validate flattened [waveform][channel][sample] AFE ramp data."""

    if waveform_count < 1:
        raise ValueError("waveform_count must be greater than zero")
    if not channels:
        raise ValueError("channels must not be empty")
    if samples_per_waveform < 2:
        raise ValueError("samples_per_waveform must be at least two")
    if max_reported_failures < 0:
        raise ValueError("max_reported_failures cannot be negative")
    if max_failures_per_channel < 0:
        raise ValueError("max_failures_per_channel cannot be negative")

    expected_words = waveform_count * len(channels) * samples_per_waveform
    if len(data) != expected_words:
        raise ValueError(
            f"Ramp data size mismatch: {len(data)} != {expected_words}"
        )

    transitions = waveform_count * len(channels) * (samples_per_waveform - 1)
    failure_count = 0
    reported: list[RampFailure] = []
    channel_examples: list[RampFailure] = []
    channel_example_counts: Counter[int] = Counter()
    waveform_failure_counts: Counter[int] = Counter()
    channel_failure_counts: Counter[int] = Counter()
    delta_failure_counts: Counter[int] = Counter()

    for waveform in range(waveform_count):
        for channel_index, channel in enumerate(channels):
            base = (
                (waveform * len(channels) + channel_index)
                * samples_per_waveform
            )
            previous = int(data[base]) & RAMP_MASK
            for sample in range(1, samples_per_waveform):
                current = int(data[base + sample]) & RAMP_MASK
                delta = (current - previous) & RAMP_MASK
                if delta != 1:
                    failure = RampFailure(
                        waveform=waveform,
                        channel=int(channel),
                        sample=sample,
                        previous=previous,
                        current=current,
                        delta=delta,
                    )
                    failure_count += 1
                    waveform_failure_counts[waveform] += 1
                    channel_failure_counts[int(channel)] += 1
                    delta_failure_counts[delta] += 1
                    if len(reported) < max_reported_failures:
                        reported.append(failure)
                    if (
                        channel_example_counts[int(channel)]
                        < max_failures_per_channel
                    ):
                        channel_examples.append(failure)
                        channel_example_counts[int(channel)] += 1
                previous = current

    return RampValidationResult(
        transitions=transitions,
        failure_count=failure_count,
        failures=tuple(reported),
        channel_failures=tuple(channel_examples),
        waveform_failure_counts=tuple(
            sorted(waveform_failure_counts.items())
        ),
        channel_failure_counts=tuple(sorted(channel_failure_counts.items())),
        delta_failure_counts=tuple(
            sorted(
                delta_failure_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
    )
