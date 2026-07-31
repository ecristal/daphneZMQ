"""Dependency-free analysis helpers for an AFE IDELAY eye sweep."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TapWindow:
    first_tap: int
    last_tap: int
    point_count: int
    recommended_tap: int


@dataclass(frozen=True)
class AfeEyeSummary:
    channel_windows: tuple[TapWindow | None, ...]
    common_window: TapWindow | None


def _validate_inputs(
    taps: Sequence[int],
    failures: Sequence[int],
    transitions: Sequence[int],
) -> None:
    if not taps:
        raise ValueError("at least one tap is required")
    if len(taps) != len(failures) or len(taps) != len(transitions):
        raise ValueError("tap, failure and transition arrays must have equal size")
    if any(right <= left for left, right in zip(taps, taps[1:])):
        raise ValueError("taps must be strictly increasing")
    if any(value <= 0 for value in transitions):
        raise ValueError("transition counts must be greater than zero")
    if any(value < 0 for value in failures):
        raise ValueError("failure counts cannot be negative")


def longest_passing_window(
    taps: Sequence[int],
    failures: Sequence[int],
    transitions: Sequence[int],
    *,
    max_error_rate: float = 0.0,
) -> TapWindow | None:
    """Return the longest consecutive tested window below an error threshold."""

    _validate_inputs(taps, failures, transitions)
    if max_error_rate < 0.0 or max_error_rate > 1.0:
        raise ValueError("max_error_rate must be in 0..1")

    best: tuple[int, int] | None = None
    run_start: int | None = None
    for index, (count, total) in enumerate(zip(failures, transitions)):
        passing = count / total <= max_error_rate
        if passing and run_start is None:
            run_start = index
        if run_start is not None and (not passing or index == len(taps) - 1):
            run_end = index if passing else index - 1
            if best is None or run_end - run_start > best[1] - best[0]:
                best = (run_start, run_end)
            run_start = None

    if best is None:
        return None
    first, last = best
    midpoint = first + (last - first) // 2
    return TapWindow(
        first_tap=int(taps[first]),
        last_tap=int(taps[last]),
        point_count=last - first + 1,
        recommended_tap=int(taps[midpoint]),
    )


def summarize_afe_eye(
    taps: Sequence[int],
    channel_failures: Sequence[Sequence[int]],
    transitions: Sequence[int],
    *,
    max_error_rate: float = 0.0,
) -> AfeEyeSummary:
    """Summarize per-channel and common passing windows for one AFE."""

    if not channel_failures:
        raise ValueError("at least one channel is required")
    channel_windows = tuple(
        longest_passing_window(
            taps,
            failures,
            transitions,
            max_error_rate=max_error_rate,
        )
        for failures in channel_failures
    )

    common_failures = []
    for point_index in range(len(taps)):
        # Use the worst channel at each tap. Comparing this value against the
        # common transition count makes a tap pass only when every lane passes.
        common_failures.append(
            max(int(failures[point_index]) for failures in channel_failures)
        )
    common_window = longest_passing_window(
        taps,
        common_failures,
        transitions,
        max_error_rate=max_error_rate,
    )
    return AfeEyeSummary(channel_windows, common_window)
