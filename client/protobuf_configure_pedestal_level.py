#!/usr/bin/env python3
"""Tune channel OFFSET DACs to a requested 14-bit pedestal level."""

import argparse
from dataclasses import dataclass, field
import math
import sys
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import zmq

try:
    import numpy as np
except ImportError:  # The client remains usable on minimal target images.
    np = None

from protobuf_loader import load_protobuf_modules
from trigger_source import configure_trigger_source
from v2_client import V2Client


CHANNEL_COUNT = 40
ADC_MIN = 0
ADC_CODE_COUNT = 1 << 14
ADC_MAX = ADC_CODE_COUNT - 1
OFFSET_MIN = 0
OFFSET_MAX = (1 << 12) - 1
INITIAL_OFFSET = 2275
PEDESTAL_WAVEFORMS = 500
MAX_ACQUISITION_BYTES = 48 * 1024 * 1024


@dataclass(frozen=True)
class Observation:
    offset: int
    pedestal: float


@dataclass
class ChannelState:
    channel: int
    current_offset: int = INITIAL_OFFSET
    observations: Dict[int, Observation] = field(default_factory=dict)
    converged: bool = False
    reason: str = ""
    iterations: int = 0

    def record(
        self,
        offset: int,
        pedestal: float,
        target: float,
        tolerance: float,
        iteration: int,
    ):
        self.current_offset = offset
        self.iterations = iteration
        self.observations[offset] = Observation(offset, pedestal)
        if abs(pedestal - target) <= tolerance:
            self.converged = True
            self.reason = "within tolerance"

    def best(self, target: float) -> Observation:
        return min(
            self.observations.values(),
            key=lambda item: (abs(item.pedestal - target), item.offset),
        )


@dataclass(frozen=True)
class CalibrationResult:
    channel: int
    offset: int
    pedestal: float
    converged: bool
    iterations: int
    reason: str
    tolerance: float = 0.0
    sensitivity: Optional[float] = None


def adc_code(value):
    parsed = int(value)
    if not ADC_MIN <= parsed <= ADC_MAX:
        raise argparse.ArgumentTypeError(
            f"expected an integer in {ADC_MIN}..{ADC_MAX}"
        )
    return parsed


def positive_int(value):
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def positive_float(value):
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive number")
    return parsed


def offset_step(value):
    parsed = positive_int(value)
    if parsed > OFFSET_MAX:
        raise argparse.ArgumentTypeError(
            f"expected an integer in 1..{OFFSET_MAX}"
        )
    return parsed


def method_name(value):
    return value.lower().replace("-", "_").replace(" ", "_")


def parse_channels(tokens: Optional[Sequence[str]], configure_all: bool) -> List[int]:
    if configure_all:
        return list(range(CHANNEL_COUNT))
    if not tokens:
        return [0]

    channels = []
    for token in tokens:
        for item in token.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                channel = int(item)
            except ValueError as exc:
                raise ValueError(f"invalid channel {item!r}") from exc
            if not 0 <= channel < CHANNEL_COUNT:
                raise ValueError(f"channel out of range 0..39: {channel}")
            if channel not in channels:
                channels.append(channel)
    if not channels:
        raise ValueError("at least one channel is required")
    return channels


def _modes_from_sums(mean_sums, waveform_count):
    result = []
    for channel_sums in mean_sums:
        counts = {}
        for value in channel_sums:
            counts[value] = counts.get(value, 0) + 1
        mode_sum = max(counts, key=lambda value: (counts[value], -value))
        result.append(mode_sum / waveform_count)
    return result


def pedestal_levels(waveforms):
    """Return the mode of each channel's 500-waveform mean vector.

    ``waveforms`` has shape ``(waveform, channel, sample)``.  Integer sums are
    used before division so values that differ by one ADC count out of 500 are
    not accidentally merged or split by floating-point rounding.
    """
    if np is not None:
        values = np.asarray(waveforms)
        if values.ndim != 3 or values.shape[0] == 0 or values.shape[2] == 0:
            raise ValueError("waveforms must have shape (W, C, N) with W,N > 0")
        if np.any(values < ADC_MIN) or np.any(values > ADC_MAX):
            raise ValueError(
                "waveform data contains values outside the 14-bit range"
            )
        mean_sums = np.sum(values, axis=0, dtype=np.int64)
        return np.asarray(
            _modes_from_sums(mean_sums, values.shape[0]), dtype=np.float64
        )

    waveform_count = len(waveforms)
    if waveform_count == 0 or not waveforms[0] or not waveforms[0][0]:
        raise ValueError("waveforms must have shape (W, C, N) with W,N > 0")
    channel_count = len(waveforms[0])
    sample_count = len(waveforms[0][0])
    mean_sums = [[0] * sample_count for _ in range(channel_count)]
    for waveform in waveforms:
        if len(waveform) != channel_count:
            raise ValueError("waveforms must be a rectangular W,C,N array")
        for channel_index, channel_samples in enumerate(waveform):
            if len(channel_samples) != sample_count:
                raise ValueError("waveforms must be a rectangular W,C,N array")
            for sample_index, value in enumerate(channel_samples):
                value = int(value)
                if not ADC_MIN <= value <= ADC_MAX:
                    raise ValueError(
                        "waveform data contains values outside the 14-bit range"
                    )
                mean_sums[channel_index][sample_index] += value
    return _modes_from_sums(mean_sums, waveform_count)


def _pedestal_levels_from_flat(data, waveform_count, channel_count, sample_count):
    if np is not None:
        values = np.asarray(data, dtype=np.int64).reshape(
            waveform_count, channel_count, sample_count
        )
        return pedestal_levels(values)

    mean_sums = [[0] * sample_count for _ in range(channel_count)]
    channel_stride = channel_count * sample_count
    for waveform_index in range(waveform_count):
        waveform_base = waveform_index * channel_stride
        for channel_index in range(channel_count):
            channel_base = waveform_base + channel_index * sample_count
            for sample_index in range(sample_count):
                value = int(data[channel_base + sample_index])
                if not ADC_MIN <= value <= ADC_MAX:
                    raise ValueError(
                        "waveform data contains values outside the 14-bit range"
                    )
                mean_sums[channel_index][sample_index] += value
    return _modes_from_sums(mean_sums, waveform_count)


def _bracket(
    state: ChannelState, target: float
) -> Optional[Tuple[Observation, Observation]]:
    below = [item for item in state.observations.values() if item.pedestal < target]
    above = [item for item in state.observations.values() if item.pedestal > target]
    pairs = [
        (low, high)
        for low in below
        for high in above
        if low.offset < high.offset
    ]
    if not pairs:
        return None
    return min(
        pairs,
        key=lambda pair: (
            pair[1].offset - pair[0].offset,
            abs(pair[0].pedestal - target) + abs(pair[1].pedestal - target),
        ),
    )


def _rail_label(pedestal: float) -> str:
    if pedestal <= ADC_MIN:
        return " SATURATED_LOW"
    if pedestal >= ADC_MAX:
        return " SATURATED_HIGH"
    return ""


def _estimated_sensitivity(
    state: ChannelState, fallback: Optional[float] = None
) -> Optional[float]:
    """Estimate the positive ADC-count change per OFFSET code."""
    points = [
        item
        for item in state.observations.values()
        if ADC_MIN < item.pedestal < ADC_MAX
    ]
    if len(points) >= 2:
        mean_offset = sum(item.offset for item in points) / len(points)
        mean_pedestal = sum(item.pedestal for item in points) / len(points)
        variance = sum((item.offset - mean_offset) ** 2 for item in points)
        if variance > 0:
            covariance = sum(
                (item.offset - mean_offset)
                * (item.pedestal - mean_pedestal)
                for item in points
            )
            slope = covariance / variance
            if slope > 0:
                return slope
    return fallback


def _accept_best(
    state: ChannelState,
    target: float,
    tolerance: float,
    reason: str,
) -> bool:
    best = state.best(target)
    if abs(best.pedestal - target) <= tolerance:
        state.converged = True
        state.reason = reason
        return True
    return False


def _resolve_initial_offsets(
    channels: Sequence[int],
    initial_offsets: Optional[Dict[int, int]],
) -> Tuple[Dict[int, int], bool]:
    if initial_offsets is None:
        return ({channel: INITIAL_OFFSET for channel in channels}, True)
    if set(initial_offsets) != set(channels):
        raise ValueError(
            "initial OFFSET map must contain exactly the selected channels"
        )
    resolved = {}
    for channel in channels:
        offset = int(initial_offsets[channel])
        if not OFFSET_MIN <= offset <= OFFSET_MAX:
            raise ValueError(
                f"channel {channel} initial OFFSET {offset} is outside "
                f"{OFFSET_MIN}..{OFFSET_MAX}"
            )
        resolved[channel] = offset
    return resolved, False


def next_offset(
    state: ChannelState,
    target: float,
    method: str,
    max_offset_step: int,
) -> Optional[int]:
    """Choose a bounded next DAC code, increasing or decreasing as needed."""
    current = state.observations[state.current_offset]
    bracket = _bracket(state, target)
    if bracket is None:
        direction = 1 if current.pedestal < target else -1
        candidate = current.offset + direction * max_offset_step
        candidate = max(OFFSET_MIN, min(OFFSET_MAX, candidate))
    else:
        low, high = bracket
        if high.offset - low.offset <= 1:
            return None
        if method == "bisection" or high.pedestal == low.pedestal:
            candidate = (low.offset + high.offset) // 2
        else:
            fraction = (target - low.pedestal) / (
                high.pedestal - low.pedestal
            )
            candidate = int(
                round(low.offset + fraction * (high.offset - low.offset))
            )
        candidate = max(low.offset + 1, min(high.offset - 1, candidate))
        delta = candidate - current.offset
        if abs(delta) > max_offset_step:
            candidate = current.offset + (
                max_offset_step if delta > 0 else -max_offset_step
            )

    candidate = max(OFFSET_MIN, min(OFFSET_MAX, candidate))
    if candidate == current.offset or candidate in state.observations:
        if bracket is None:
            return None
        low, high = bracket
        eligible = [
            offset
            for offset in range(low.offset + 1, high.offset)
            if offset not in state.observations
            and abs(offset - current.offset) <= max_offset_step
        ]
        if not eligible:
            return None
        candidate = min(
            eligible,
            key=lambda offset: (
                abs(offset - candidate),
                abs(offset - current.offset),
            ),
        )
    return candidate


def calibrate_pedestals(
    channels: Sequence[int],
    target: float,
    method: str,
    max_iterations: int,
    max_offset_step: int,
    tolerance: float,
    write_offset: Callable[[int, int], None],
    measure_pedestals: Callable[[Sequence[int]], Dict[int, float]],
    report: Optional[Callable[[str], None]] = print,
    initial_offsets: Optional[Dict[int, int]] = None,
) -> List[CalibrationResult]:
    """Calibrate selected channels concurrently and leave each at its best offset."""
    if method not in ("bisection", "regula_falsi"):
        raise ValueError(f"unsupported method {method!r}")
    if max_iterations <= 0 or max_offset_step <= 0 or tolerance <= 0:
        raise ValueError("iteration count, offset step, and tolerance must be positive")

    resolved_offsets, configure_initial = _resolve_initial_offsets(
        channels, initial_offsets
    )
    states = {
        channel: ChannelState(channel, current_offset=resolved_offsets[channel])
        for channel in channels
    }
    active = list(channels)
    for iteration in range(1, max_iterations + 1):
        if iteration > 1 or configure_initial:
            for channel in active:
                write_offset(channel, states[channel].current_offset)

        measured = measure_pedestals(active)
        if set(measured) != set(active):
            raise RuntimeError(
                "pedestal acquisition returned a different channel set: "
                f"expected {active}, got {sorted(measured)}"
            )

        next_active = []
        for channel in active:
            state = states[channel]
            pedestal = float(measured[channel])
            state.record(
                state.current_offset, pedestal, target, tolerance, iteration
            )
            error = pedestal - target
            rail = ""
            if pedestal <= ADC_MIN:
                rail = " SATURATED_LOW"
            elif pedestal >= ADC_MAX:
                rail = " SATURATED_HIGH"
            if report is not None:
                report(
                    f"iteration={iteration:02d} channel={channel:02d} "
                    f"offset={state.current_offset:04d} pedestal={pedestal:.3f} "
                    f"error={error:+.3f}{rail}"
                )
            if state.converged:
                continue

            if iteration == max_iterations:
                next_active.append(channel)
                continue

            candidate = next_offset(state, target, method, max_offset_step)
            if candidate is None:
                bracket = _bracket(state, target)
                if state.current_offset == OFFSET_MIN:
                    state.reason = "lower offset limit reached"
                elif state.current_offset == OFFSET_MAX:
                    state.reason = "upper offset limit reached"
                elif bracket is not None and (
                    bracket[1].offset - bracket[0].offset <= 1
                ):
                    state.reason = "adjacent DAC codes bracket target"
                else:
                    state.reason = "no unmeasured bounded step remains"
                continue
            state.current_offset = candidate
            next_active.append(channel)

        active = next_active
        if not active:
            break

    for channel in active:
        states[channel].reason = "maximum iterations reached"

    results = []
    for channel in channels:
        state = states[channel]
        best = state.best(target)
        while state.current_offset != best.offset:
            delta = best.offset - state.current_offset
            step = max(-max_offset_step, min(max_offset_step, delta))
            state.current_offset += step
            write_offset(channel, state.current_offset)
        results.append(
            CalibrationResult(
                channel=channel,
                offset=best.offset,
                pedestal=best.pedestal,
                converged=state.converged,
                iterations=state.iterations,
                reason=state.reason,
                tolerance=tolerance,
            )
        )
    return results


def _auto_next_offset(
    state: ChannelState,
    target: float,
    method: str,
    sensitivity: float,
) -> Optional[int]:
    bracket = _bracket(state, target)
    if bracket is not None:
        return next_offset(state, target, method, OFFSET_MAX)

    current = state.observations[state.current_offset]
    slope = _estimated_sensitivity(state, sensitivity)
    if slope is None or slope <= 0:
        return None
    raw_candidate = current.offset + (target - current.pedestal) / slope
    candidate = int(round(raw_candidate))
    candidate = max(OFFSET_MIN, min(OFFSET_MAX, candidate))
    if candidate == current.offset:
        direction = 1 if current.pedestal < target else -1
        candidate = max(
            OFFSET_MIN, min(OFFSET_MAX, current.offset + direction)
        )
    if candidate not in state.observations:
        return candidate

    eligible = [
        offset
        for offset in range(OFFSET_MIN, OFFSET_MAX + 1)
        if offset not in state.observations
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda offset: abs(offset - raw_candidate))


def calibrate_pedestals_auto(
    channels: Sequence[int],
    target: float,
    method: str,
    minimum_tolerance: float,
    write_offset: Callable[[int, int], None],
    measure_pedestals: Callable[[Sequence[int]], Dict[int, float]],
    report: Optional[Callable[[str], None]] = print,
    initial_offsets: Optional[Dict[int, int]] = None,
) -> List[CalibrationResult]:
    """Measure channel sensitivity, then tune with fully automatic bounds."""
    if method not in ("bisection", "regula_falsi"):
        raise ValueError(f"unsupported method {method!r}")
    if minimum_tolerance <= 0:
        raise ValueError("minimum tolerance must be positive")

    resolved_offsets, configure_initial = _resolve_initial_offsets(
        channels, initial_offsets
    )
    states = {
        channel: ChannelState(channel, current_offset=resolved_offsets[channel])
        for channel in channels
    }
    sensitivities: Dict[int, float] = {}
    tolerances = {channel: minimum_tolerance for channel in channels}

    def measure_offsets(selected, offsets, phase, configure=True):
        if configure:
            for channel in selected:
                write_offset(channel, offsets[channel])
        measured = measure_pedestals(selected)
        if set(measured) != set(selected):
            raise RuntimeError(
                "pedestal acquisition returned a different channel set: "
                f"expected {list(selected)}, got {sorted(measured)}"
            )
        for channel in selected:
            pedestal = float(measured[channel])
            if not math.isfinite(pedestal) or not ADC_MIN <= pedestal <= ADC_MAX:
                raise RuntimeError(
                    f"channel {channel} returned invalid 14-bit pedestal "
                    f"{pedestal}"
                )
            state = states[channel]
            state.current_offset = offsets[channel]
            state.iterations += 1
            state.observations[offsets[channel]] = Observation(
                offsets[channel], pedestal
            )
            if report is not None:
                report(
                    f"phase={phase:<11} channel={channel:02d} "
                    f"offset={offsets[channel]:04d} pedestal={pedestal:.3f} "
                    f"error={pedestal - target:+.3f}{_rail_label(pedestal)}"
                )

    measure_offsets(
        channels,
        resolved_offsets,
        "initial",
        configure=configure_initial,
    )

    probe_origins = {
        channel: states[channel].observations[resolved_offsets[channel]]
        for channel in channels
    }
    probe_directions = {}
    probe_spans = {channel: 1 for channel in channels}
    probing = list(channels)
    search_channels = []

    for channel in channels:
        pedestal = probe_origins[channel].pedestal
        if pedestal <= ADC_MIN:
            probe_directions[channel] = 1
        elif pedestal >= ADC_MAX:
            probe_directions[channel] = -1
        else:
            probe_directions[channel] = 1 if pedestal <= target else -1

    while probing:
        probe_offsets = {}
        measurable = []
        for channel in probing:
            origin = probe_origins[channel]
            direction = probe_directions[channel]
            candidate = origin.offset + direction * probe_spans[channel]
            candidate = max(OFFSET_MIN, min(OFFSET_MAX, candidate))
            if candidate == origin.offset:
                state = states[channel]
                if not _accept_best(
                    state,
                    target,
                    minimum_tolerance,
                    "target reached at ADC rail; sensitivity unavailable",
                ):
                    state.reason = (
                        "no OFFSET range available for sensitivity probe"
                    )
                continue
            probe_offsets[channel] = candidate
            measurable.append(channel)

        if not measurable:
            break
        measure_offsets(measurable, probe_offsets, "sensitivity")

        next_probing = []
        for channel in measurable:
            origin = probe_origins[channel]
            observation = states[channel].observations[probe_offsets[channel]]
            offset_delta = observation.offset - origin.offset
            pedestal_delta = observation.pedestal - origin.pedestal
            sensitivity = pedestal_delta / offset_delta
            minimum_signal = max(1.0, 2.0 * minimum_tolerance)
            if sensitivity > 0 and abs(pedestal_delta) >= minimum_signal:
                sensitivities[channel] = sensitivity
                tolerances[channel] = max(
                    minimum_tolerance, abs(sensitivity) / 2.0
                )
                if report is not None:
                    report(
                        f"[AUTO] channel={channel:02d} "
                        f"sensitivity={sensitivity:.3f} ADC/OFFSET "
                        f"tolerance={tolerances[channel]:.3f}"
                    )
                if not _accept_best(
                    states[channel],
                    target,
                    tolerances[channel],
                    "within automatic quantization tolerance",
                ):
                    search_channels.append(channel)
                continue

            at_limit = observation.offset in (OFFSET_MIN, OFFSET_MAX)
            if at_limit:
                state = states[channel]
                if not _accept_best(
                    state,
                    target,
                    minimum_tolerance,
                    "target reached at ADC rail; sensitivity unavailable",
                ):
                    state.reason = (
                        "could not measure positive OFFSET sensitivity before "
                        "reaching the DAC limit"
                    )
                continue
            probe_spans[channel] *= 2
            next_probing.append(channel)

        probing = next_probing

    search_round_limit = math.ceil(math.log2(OFFSET_MAX - OFFSET_MIN + 1)) + 3
    active = search_channels
    for _ in range(search_round_limit):
        if not active:
            break
        offsets = {}
        measurable = []
        for channel in active:
            state = states[channel]
            bracket = _bracket(state, target)
            if bracket is not None and bracket[1].offset - bracket[0].offset <= 1:
                adjacent_sensitivity = abs(
                    bracket[1].pedestal - bracket[0].pedestal
                )
                if adjacent_sensitivity > 0:
                    sensitivities[channel] = adjacent_sensitivity
                tolerances[channel] = max(
                    minimum_tolerance, adjacent_sensitivity / 2.0
                )
                if _accept_best(
                    state,
                    target,
                    tolerances[channel],
                    "best achievable at adjacent OFFSET codes",
                ):
                    continue

            sensitivity = _estimated_sensitivity(
                state, sensitivities[channel]
            )
            if sensitivity is not None:
                sensitivities[channel] = sensitivity
                tolerances[channel] = max(
                    minimum_tolerance, abs(sensitivity) / 2.0
                )
            candidate = _auto_next_offset(
                state, target, method, sensitivities[channel]
            )
            if candidate is None:
                if state.current_offset == OFFSET_MIN:
                    state.reason = "lower OFFSET limit reached"
                elif state.current_offset == OFFSET_MAX:
                    state.reason = "upper OFFSET limit reached"
                else:
                    state.reason = "no unmeasured automatic step remains"
                continue
            offsets[channel] = candidate
            measurable.append(channel)
            if report is not None:
                report(
                    f"[AUTO] channel={channel:02d} next_offset={candidate:04d} "
                    f"change={candidate - state.current_offset:+d}"
                )

        if not measurable:
            active = []
            break
        measure_offsets(measurable, offsets, "search")

        next_active = []
        for channel in measurable:
            state = states[channel]
            sensitivity = _estimated_sensitivity(
                state, sensitivities[channel]
            )
            if sensitivity is not None:
                sensitivities[channel] = sensitivity
                tolerances[channel] = max(
                    minimum_tolerance, abs(sensitivity) / 2.0
                )
            if _accept_best(
                state,
                target,
                tolerances[channel],
                "within automatic quantization tolerance",
            ):
                continue
            next_active.append(channel)
        active = next_active

    for channel in active:
        states[channel].reason = "automatic search limit reached"

    results = []
    for channel in channels:
        state = states[channel]
        best = state.best(target)
        if state.current_offset != best.offset:
            write_offset(channel, best.offset)
            state.current_offset = best.offset
        results.append(
            CalibrationResult(
                channel=channel,
                offset=best.offset,
                pedestal=best.pedestal,
                converged=state.converged,
                iterations=state.iterations,
                reason=state.reason,
                tolerance=tolerances[channel],
                sensitivity=sensitivities.get(channel),
            )
        )
    return results


def _read_current_offsets(pb_high, pb_low, client, channels: Sequence[int]):
    response = client.rpc(
        pb_high.MT2_READ_OFFSET_ALL_CH_REQ,
        pb_low.cmd_readOffset_allChannels(),
        pb_high.MT2_READ_OFFSET_ALL_CH_RESP,
        pb_low.cmd_readOffset_allChannels_response,
    )
    if not response.success:
        raise RuntimeError(f"could not read channel OFFSETs: {response.message}")
    values = list(response.offsetValues)
    if len(values) != CHANNEL_COUNT:
        raise RuntimeError(
            f"OFFSET readback returned {len(values)} channels; "
            f"expected {CHANNEL_COUNT}"
        )
    offsets = {}
    for channel in channels:
        offset = int(values[channel])
        if not OFFSET_MIN <= offset <= OFFSET_MAX:
            raise RuntimeError(
                f"channel {channel} OFFSET readback {offset} is outside "
                f"{OFFSET_MIN}..{OFFSET_MAX}"
            )
        offsets[channel] = offset
    return offsets


def _verify_configured_offsets(pb_high, pb_low, client, expected_offsets):
    channels = list(expected_offsets)
    actual_offsets = _read_current_offsets(
        pb_high, pb_low, client, channels
    )
    mismatches = {
        channel: (int(expected_offsets[channel]), actual_offsets[channel])
        for channel in channels
        if actual_offsets[channel] != int(expected_offsets[channel])
    }
    if mismatches:
        details = ", ".join(
            f"ch{channel}: expected {expected}, read {actual}"
            for channel, (expected, actual) in mismatches.items()
        )
        raise RuntimeError(f"final OFFSET verification failed: {details}")
    return actual_offsets


def _write_offset(pb_high, pb_low, client, channel: int, offset: int):
    request = pb_low.cmd_writeOFFSET_singleChannel(
        offsetChannel=channel,
        offsetValue=offset,
        offsetGain=False,
    )
    response = client.rpc(
        pb_high.MT2_WRITE_OFFSET_CH_REQ,
        request,
        pb_high.MT2_WRITE_OFFSET_CH_RESP,
        pb_low.cmd_writeOFFSET_singleChannel_response,
    )
    if not response.success:
        raise RuntimeError(
            f"could not set channel {channel} offset {offset}: {response.message}"
        )
    if response.offsetValue != offset:
        raise RuntimeError(
            f"channel {channel} offset readback {response.offsetValue} != {offset}"
        )


def _measure_pedestal_batch(pb_high, client, channels: Sequence[int], samples: int):
    request = pb_high.DumpSpyBuffersRequest()
    request.channelList.extend(channels)
    request.numberOfWaveforms = PEDESTAL_WAVEFORMS
    request.numberOfSamples = samples
    request.softwareTrigger = True
    response = client.rpc(
        pb_high.MT2_DUMP_SPYBUFFER_REQ,
        request,
        pb_high.MT2_DUMP_SPYBUFFER_RESP,
        pb_high.DumpSpyBuffersResponse,
    )
    if not response.success:
        raise RuntimeError(f"pedestal acquisition failed: {response.message}")
    if list(response.channelList) != list(channels):
        raise RuntimeError("acquisition response channel list does not match request")
    if response.numberOfWaveforms != PEDESTAL_WAVEFORMS:
        raise RuntimeError(
            "acquisition response waveform count does not match "
            f"{PEDESTAL_WAVEFORMS}"
        )
    if response.numberOfSamples != samples:
        raise RuntimeError("acquisition response sample count does not match request")
    if not response.softwareTrigger:
        raise RuntimeError("acquisition response did not use software trigger")

    expected = PEDESTAL_WAVEFORMS * len(channels) * samples
    if len(response.data) != expected:
        raise RuntimeError(
            f"acquisition returned {len(response.data)} samples; expected {expected}"
        )
    values = _pedestal_levels_from_flat(
        response.data, PEDESTAL_WAVEFORMS, len(channels), samples
    )
    return {channel: float(values[index]) for index, channel in enumerate(channels)}


def _measure_pedestals(pb_high, client, channels: Sequence[int], samples: int):
    bytes_per_channel = PEDESTAL_WAVEFORMS * samples * 4
    channels_per_request = MAX_ACQUISITION_BYTES // bytes_per_channel
    if channels_per_request < 1:
        raise RuntimeError(
            f"waveform length {samples} makes one 500-waveform channel exceed "
            "the safe non-streaming response size"
        )

    result = {}
    for start in range(0, len(channels), channels_per_request):
        batch = channels[start : start + channels_per_request]
        result.update(_measure_pedestal_batch(pb_high, client, batch, samples))
    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Tune DAPHNE channel offsets so the measured 14-bit pedestal "
            "matches a target. Each measurement averages 500 software-triggered "
            "waveforms and takes the mode of the mean waveform."
        )
    )
    parser.add_argument("-ip", "--ip", default="127.0.0.1")
    parser.add_argument("-port", "--port", type=int, default=9876)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "-channel",
        "--channel",
        "-channel_list",
        "--channel-list",
        nargs="+",
        metavar="CHANNEL",
        help="One or more channels (space- or comma-separated; default: 0).",
    )
    selection.add_argument(
        "-configure_all",
        "--configure-all",
        action="store_true",
        help="Configure all 40 channels.",
    )
    parser.add_argument(
        "--use-current-offset",
        "--use_current_offset",
        action="store_true",
        dest="use_current_offset",
        help=(
            "Use each channel's current OFFSET for the initial pedestal "
            "measurement instead of writing 2275."
        ),
    )
    parser.add_argument(
        "--use_init_current_pedestal",
        "--use-init-current-pedestal",
        action="store_true",
        dest="use_current_offset",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-target_pedestal",
        "--target-pedestal",
        type=adc_code,
        required=True,
        help=f"Target pedestal in {ADC_MIN}..{ADC_MAX} ADC counts.",
    )
    parser.add_argument(
        "-method",
        "--method",
        type=method_name,
        choices=("bisection", "regula_falsi"),
        default="regula_falsi",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Measure OFFSET sensitivity per channel and automatically derive "
            "the tolerance, iteration budget, and offset changes."
        ),
    )
    parser.add_argument(
        "-max_iterations",
        "--max-iterations",
        dest="max_iterations",
        type=positive_int,
        default=None,
        help="Manual-mode iteration limit (default: 16).",
    )
    parser.add_argument(
        "-max_offset_change",
        "--max-offset-change",
        dest="max_offset_change",
        type=offset_step,
        default=None,
        help="Manual-mode OFFSET change limit (default: 512).",
    )
    parser.add_argument(
        "-max_iteration_steps",
        "--max-iteration-steps",
        dest="max_iterations",
        type=positive_int,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-max_iteration_offset",
        "--max-iteration-offset",
        "--max-offset-step",
        dest="max_offset_change",
        type=offset_step,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-L",
        "--samples",
        type=positive_int,
        required=True,
        help="Samples in each of the 500 waveforms.",
    )
    parser.add_argument(
        "--tolerance",
        type=positive_float,
        default=1.0,
        help=(
            "Allowed error in manual mode, or minimum tolerance with --auto "
            "(default: 1 ADC count)."
        ),
    )
    parser.add_argument("-route", "--route", "-r", default="mezz/0")
    parser.add_argument(
        "--timeout-ms", "--timeout_ms", type=positive_int, default=30000
    )
    parser.add_argument("--identity", default="configure-pedestal-v2")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        channels = parse_channels(args.channel, args.configure_all)
    except ValueError as exc:
        parser.error(str(exc))
    if args.auto and (
        args.max_iterations is not None or args.max_offset_change is not None
    ):
        parser.error(
            "--auto calculates iteration and OFFSET changes; do not combine it "
            "with --max-iterations or --max-offset-change"
        )

    try:
        pb_high, pb_low = load_protobuf_modules(require_trigger_source=True)
        with V2Client(
            pb_high,
            args.ip,
            args.port,
            route=args.route,
            timeout_ms=args.timeout_ms,
            identity=args.identity,
        ) as client:
            def send_trigger_request(message_type, payload):
                response = client.request(message_type, payload)
                return response.type, response.payload

            configure_trigger_source(
                pb_high, send_trigger_request, "software"
            )
            print("Configured spybuffer trigger source: software")

            initial_offsets = None
            if args.use_current_offset:
                initial_offsets = _read_current_offsets(
                    pb_high, pb_low, client, channels
                )
                summary = ", ".join(
                    f"ch{channel}={initial_offsets[channel]}"
                    for channel in channels
                )
                print(
                    "Using current OFFSET configuration for initial "
                    f"measurement: {summary}"
                )

            def write_offset(channel, offset):
                return _write_offset(
                    pb_high, pb_low, client, channel, offset
                )

            def measure_pedestals(selected):
                return _measure_pedestals(
                    pb_high, client, selected, args.samples
                )

            if args.auto:
                results = calibrate_pedestals_auto(
                    channels=channels,
                    target=args.target_pedestal,
                    method=args.method,
                    minimum_tolerance=args.tolerance,
                    write_offset=write_offset,
                    measure_pedestals=measure_pedestals,
                    initial_offsets=initial_offsets,
                )
            else:
                results = calibrate_pedestals(
                    channels=channels,
                    target=args.target_pedestal,
                    method=args.method,
                    max_iterations=args.max_iterations or 16,
                    max_offset_step=args.max_offset_change or 512,
                    tolerance=args.tolerance,
                    write_offset=write_offset,
                    measure_pedestals=measure_pedestals,
                    initial_offsets=initial_offsets,
                )

            expected_offsets = {
                result.channel: result.offset for result in results
            }
            verified_offsets = _verify_configured_offsets(
                pb_high, pb_low, client, expected_offsets
            )
            summary = ", ".join(
                f"ch{channel}={verified_offsets[channel]}"
                for channel in channels
            )
            print(f"Verified final OFFSET readback: {summary}")
    except (RuntimeError, TimeoutError, ValueError, zmq.ZMQError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    failed = False
    for result in results:
        status = "PASS" if result.converged else "FAIL"
        auto_details = ""
        if args.auto:
            sensitivity = (
                "unavailable"
                if result.sensitivity is None
                else f"{result.sensitivity:.3f} ADC/OFFSET"
            )
            auto_details = (
                f" sensitivity={sensitivity} tolerance={result.tolerance:.3f}"
            )
        print(
            f"[{status}] channel {result.channel:02d} offset={result.offset:04d} "
            f"pedestal={result.pedestal:.3f} target={args.target_pedestal} "
            f"({result.reason}){auto_details}"
        )
        failed = failed or not result.converged
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
