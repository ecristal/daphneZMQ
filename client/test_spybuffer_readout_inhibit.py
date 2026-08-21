#!/usr/bin/env python3
"""AFE-ramp smoke test for protected normal and chunked spybuffer readout."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import random
import time
import uuid

import zmq

from protobuf_loader import load_protobuf_modules
from spybuffer_failure_artifacts import FailureArtifactWriter
from spybuffer_ramp_validation import validate_ramp_data
from trigger_source import (
    add_trigger_source_arguments,
    configure_trigger_source,
    read_trigger_source,
    resolve_trigger_source,
)


UINT64_MASK = (1 << 64) - 1
UINT64_HALF_RANGE = 1 << 63


pb_high, pb_low = load_protobuf_modules(require_trigger_source=True)


def parse_channels(spec: str) -> list[int]:
    channels: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            first_text, last_text = token.split("-", 1)
            first, last = int(first_text), int(last_text)
            if last < first:
                raise ValueError(f"Descending channel range: {token}")
            channels.extend(range(first, last + 1))
        else:
            channels.append(int(token))

    channels = list(dict.fromkeys(channels))
    if not channels:
        raise ValueError("At least one channel is required")
    invalid = [channel for channel in channels if channel < 0 or channel > 39]
    if invalid:
        raise ValueError(f"Channels outside 0..39: {invalid}")
    return channels


def next_ids() -> tuple[int, int]:
    now = time.time_ns()
    mask = (1 << 63) - 1
    return (
        ((now << 7) ^ random.getrandbits(31)) & mask,
        ((now << 1) ^ random.getrandbits(31)) & mask,
    )


def make_socket(
    context: zmq.Context,
    endpoint: str,
    timeout_ms: int,
    identity_prefix: str,
) -> zmq.Socket:
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(
        zmq.IDENTITY,
        f"{identity_prefix}-{uuid.uuid4()}".encode("ascii"),
    )
    socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
    socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
    socket.connect(endpoint)
    return socket


def make_envelope(message_type: int, payload: bytes, route: str):
    envelope = pb_high.ControlEnvelopeV2()
    envelope.version = 2
    envelope.dir = pb_high.DIR_REQUEST
    envelope.type = message_type
    envelope.payload = payload
    envelope.task_id, envelope.msg_id = next_ids()
    envelope.timestamp_ns = time.time_ns()
    envelope.route = route
    return envelope


def receive_envelope(socket: zmq.Socket, request_envelope):
    frames = [socket.recv()]
    while socket.getsockopt(zmq.RCVMORE):
        frames.append(socket.recv())

    reply = pb_high.ControlEnvelopeV2()
    if not reply.ParseFromString(frames[-1]):
        raise RuntimeError("Could not parse ControlEnvelopeV2 response")
    if reply.dir != pb_high.DIR_RESPONSE:
        raise RuntimeError(f"Unexpected response direction: {reply.dir}")
    if reply.correl_id != request_envelope.msg_id:
        raise RuntimeError(
            f"Correlation mismatch: {reply.correl_id} != "
            f"{request_envelope.msg_id}"
        )
    return reply


def v2_request(
    socket: zmq.Socket,
    request_type: int,
    response_type: int,
    payload: bytes,
    route: str,
):
    envelope = make_envelope(request_type, payload, route)
    socket.send(envelope.SerializeToString())
    reply = receive_envelope(socket, envelope)
    if reply.type != response_type:
        raise RuntimeError(
            f"Unexpected response type {reply.type}; expected {response_type}"
        )
    return reply


def set_afe_function(
    socket: zmq.Socket,
    route: str,
    afe: int,
    function: str,
    value: int,
) -> None:
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = function
    request.configValue = value
    reply = v2_request(
        socket,
        pb_high.MT2_WRITE_AFE_FUNCTION_REQ,
        pb_high.MT2_WRITE_AFE_FUNCTION_RESP,
        request.SerializeToString(),
        route,
    )

    response = pb_low.cmd_writeAFEFunction_response()
    if not response.ParseFromString(reply.payload):
        raise RuntimeError("Could not parse cmd_writeAFEFunction_response")
    if not response.success:
        raise RuntimeError(
            f"AFE{afe} rejected {function}={value}: {response.message}"
        )
    if response.configValue != value:
        raise RuntimeError(
            f"AFE{afe} {function} readback {response.configValue} != {value}"
        )
    print(f"[AFE] AFE{afe} {function}={value}")


def set_all_afes(
    socket: zmq.Socket,
    route: str,
    function: str,
    value: int,
    *,
    best_effort: bool = False,
) -> list[str]:
    errors: list[str] = []
    for afe in range(5):
        try:
            set_afe_function(socket, route, afe, function, value)
        except Exception as error:
            message = f"AFE{afe} {function}={value}: {error}"
            errors.append(message)
            if not best_effort:
                raise RuntimeError(message) from error
    return errors


def configure_ramp(socket: zmq.Socket, route: str) -> None:
    set_all_afes(socket, route, "SYNC_PATTERN", 1)
    set_all_afes(socket, route, "TEST_PATTERN_MODES", 7)


def disable_ramp(socket: zmq.Socket, route: str) -> list[str]:
    errors = set_all_afes(
        socket,
        route,
        "TEST_PATTERN_MODES",
        0,
        best_effort=True,
    )
    errors.extend(
        set_all_afes(
            socket,
            route,
            "SYNC_PATTERN",
            0,
            best_effort=True,
        )
    )
    return errors


def require_response_metadata(
    response,
    channels: list[int],
    samples: int,
    waveforms: int,
) -> None:
    if not response.success:
        raise RuntimeError(f"Server rejected acquisition: {response.message}")
    if list(response.channelList) != channels:
        raise RuntimeError(
            f"Channel list mismatch: {list(response.channelList)} != {channels}"
        )
    if response.numberOfSamples != samples:
        raise RuntimeError(
            f"Sample count mismatch: {response.numberOfSamples} != {samples}"
        )
    if len(response.timestamps) != waveforms:
        raise RuntimeError(
            f"Timestamp count mismatch: {len(response.timestamps)} != {waveforms}"
        )


@dataclass
class AcquisitionStats:
    timestamps: list[int]
    transitions: int
    ramp_failures: int
    channel_failure_counts: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class TimestampFailure:
    waveform: int
    kind: str
    previous: int
    current: int
    delta: int


def acquire_normal(
    socket: zmq.Socket,
    route: str,
    channels: list[int],
    samples: int,
    waveforms: int,
    software_trigger: bool,
    max_stored_failures: int,
    plots_per_channel: int,
    artifacts: FailureArtifactWriter,
) -> AcquisitionStats:
    request = pb_high.DumpSpyBuffersRequest()
    request.channelList.extend(channels)
    request.numberOfSamples = samples
    request.numberOfWaveforms = waveforms
    request.softwareTrigger = software_trigger

    reply = v2_request(
        socket,
        pb_high.MT2_DUMP_SPYBUFFER_REQ,
        pb_high.MT2_DUMP_SPYBUFFER_RESP,
        request.SerializeToString(),
        route,
    )
    response = pb_high.DumpSpyBuffersResponse()
    if not response.ParseFromString(reply.payload):
        raise RuntimeError("Could not parse DumpSpyBuffersResponse")
    require_response_metadata(response, channels, samples, waveforms)
    if response.numberOfWaveforms != waveforms:
        raise RuntimeError(
            f"Normal response returned {response.numberOfWaveforms} waveforms; "
            f"expected {waveforms}"
        )
    if response.softwareTrigger != software_trigger:
        raise RuntimeError(
            "Normal response trigger mode does not match the request"
        )

    result = validate_ramp_data(
        response.data,
        waveforms,
        channels,
        samples,
        max_reported_failures=max_stored_failures,
        max_failures_per_channel=plots_per_channel,
    )
    artifacts.record_ramp_result(
        "normal",
        response.data,
        waveforms,
        channels,
        samples,
        result,
    )
    return AcquisitionStats(
        timestamps=[int(value) for value in response.timestamps],
        transitions=result.transitions,
        ramp_failures=result.failure_count,
        channel_failure_counts=result.channel_failure_counts,
    )


def prime_hardware_trigger_cursor(
    socket: zmq.Socket,
    route: str,
    channel: int,
) -> None:
    """Discard one snapshot after changing AFE test-pattern configuration."""

    request = pb_high.DumpSpyBuffersRequest()
    request.channelList.append(channel)
    request.numberOfSamples = 2
    request.numberOfWaveforms = 1
    request.softwareTrigger = False

    reply = v2_request(
        socket,
        pb_high.MT2_DUMP_SPYBUFFER_REQ,
        pb_high.MT2_DUMP_SPYBUFFER_RESP,
        request.SerializeToString(),
        route,
    )
    response = pb_high.DumpSpyBuffersResponse()
    if not response.ParseFromString(reply.payload):
        raise RuntimeError("Could not parse hardware-prime response")
    require_response_metadata(response, [channel], 2, 1)
    if response.numberOfWaveforms != 1:
        raise RuntimeError("Hardware-prime response did not contain one waveform")

    print(
        "[PRIME] discarded post-configuration hardware snapshot "
        f"timestamp=0x{int(response.timestamps[0]):016X}"
    )


def acquire_chunked(
    socket: zmq.Socket,
    route: str,
    channels: list[int],
    samples: int,
    waveforms: int,
    chunk_size: int,
    software_trigger: bool,
    max_stored_failures: int,
    plots_per_channel: int,
    artifacts: FailureArtifactWriter,
) -> AcquisitionStats:
    request = pb_high.DumpSpyBuffersChunkRequest()
    request.channelList.extend(channels)
    request.numberOfSamples = samples
    request.numberOfWaveforms = waveforms
    request.softwareTrigger = software_trigger
    request.requestID = str(uuid.uuid4())
    request.chunkSize = chunk_size

    envelope = make_envelope(
        pb_high.MT2_DUMP_SPYBUFFER_CHUNK_REQ,
        request.SerializeToString(),
        route,
    )
    socket.send(envelope.SerializeToString())

    expected_sequence = 0
    expected_waveform_start = 0
    timestamps: list[int] = []
    transitions = 0
    ramp_failures = 0
    channel_failure_counts: Counter[int] = Counter()

    while True:
        reply = receive_envelope(socket, envelope)
        if reply.type != pb_high.MT2_DUMP_SPYBUFFER_CHUNK_RESP:
            raise RuntimeError(
                f"Unexpected chunk response type: {reply.type}"
            )

        chunk = pb_high.DumpSpyBuffersChunkResponse()
        if not chunk.ParseFromString(reply.payload):
            raise RuntimeError("Could not parse DumpSpyBuffersChunkResponse")
        if not chunk.success:
            raise RuntimeError(f"Server rejected chunk: {chunk.message}")
        if chunk.requestID != request.requestID:
            raise RuntimeError(
                f"Chunk request ID mismatch: {chunk.requestID} != "
                f"{request.requestID}"
            )
        if chunk.chunkseq != expected_sequence:
            raise RuntimeError(
                f"Chunk sequence mismatch: {chunk.chunkseq} != "
                f"{expected_sequence}"
            )
        if chunk.waveformStart != expected_waveform_start:
            raise RuntimeError(
                f"Chunk waveform start mismatch: {chunk.waveformStart} != "
                f"{expected_waveform_start}"
            )
        if chunk.requestTotalWaveforms != waveforms:
            raise RuntimeError("Chunk total waveform count mismatch")

        chunk_waveforms = int(chunk.waveformCount)
        require_response_metadata(
            chunk,
            channels,
            samples,
            chunk_waveforms,
        )
        result = validate_ramp_data(
            chunk.data,
            chunk_waveforms,
            channels,
            samples,
            max_reported_failures=max_stored_failures,
            max_failures_per_channel=plots_per_channel,
        )
        artifacts.record_ramp_result(
            "chunked",
            chunk.data,
            chunk_waveforms,
            channels,
            samples,
            result,
            waveform_offset=int(chunk.waveformStart),
        )
        ramp_failures += result.failure_count
        channel_failure_counts.update(dict(result.channel_failure_counts))
        transitions += result.transitions
        timestamps.extend(int(value) for value in chunk.timestamps)

        expected_sequence += 1
        expected_waveform_start += chunk_waveforms
        if chunk.isFinal:
            break

    if expected_waveform_start != waveforms:
        raise RuntimeError(
            f"Chunked waveform count mismatch: "
            f"{expected_waveform_start} != {waveforms}"
        )
    return AcquisitionStats(
        timestamps=timestamps,
        transitions=transitions,
        ramp_failures=ramp_failures,
        channel_failure_counts=tuple(sorted(channel_failure_counts.items())),
    )


def timestamp_failures(timestamps: list[int]) -> list[TimestampFailure]:
    failures: list[TimestampFailure] = []
    for index in range(1, len(timestamps)):
        previous = timestamps[index - 1]
        current = timestamps[index]
        delta = (current - previous) & UINT64_MASK
        if delta == 0:
            failures.append(
                TimestampFailure(
                    waveform=index,
                    kind="duplicate",
                    previous=previous,
                    current=current,
                    delta=delta,
                )
            )
        elif delta >= UINT64_HALF_RANGE:
            failures.append(
                TimestampFailure(
                    waveform=index,
                    kind="non-monotonic",
                    previous=previous,
                    current=current,
                    delta=delta,
                )
            )
    return failures


def format_channel_ranges(channels: list[int]) -> str:
    if not channels:
        return "none"

    ranges: list[str] = []
    first = previous = channels[0]
    for channel in channels[1:]:
        if channel == previous + 1:
            previous = channel
            continue
        ranges.append(str(first) if first == previous else f"{first}-{previous}")
        first = previous = channel
    ranges.append(str(first) if first == previous else f"{first}-{previous}")
    return ",".join(ranges)


def report_channel_status(
    label: str,
    stats: AcquisitionStats,
    requested_channels: list[int],
) -> None:
    failure_counts = dict(stats.channel_failure_counts)
    failed_channels = [
        channel for channel in requested_channels if channel in failure_counts
    ]
    passed_channels = [
        channel for channel in requested_channels if channel not in failure_counts
    ]

    if not failed_channels:
        print(
            f"[PASS] {label} ramp: all {len(requested_channels)} channels passed; "
            f"transitions={stats.transitions}"
        )
        return

    failed_summary = ", ".join(
        f"ch{channel} ({failure_counts[channel]} failures)"
        for channel in failed_channels
    )
    print(
        f"[FAIL] {label} ramp: "
        f"{len(failed_channels)}/{len(requested_channels)} "
        f"channels failed; ramp_failures={stats.ramp_failures}"
    )
    print(f"       failed channels: {failed_summary}")
    print(
        f"[PASS] {label} ramp: "
        f"{len(passed_channels)}/{len(requested_channels)} "
        f"channels passed: {format_channel_ranges(passed_channels)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Configure the AFE5808A ramp, verify protected spybuffer "
            "readout, and restore normal AFE output."
        )
    )
    parser.add_argument("--ip", "-ip", default="127.0.0.1")
    parser.add_argument("--port", "-port", type=int, default=9876)
    parser.add_argument("--route", default="mezz/0")
    parser.add_argument("--channels", default="0-39")
    parser.add_argument("--samples", type=int, default=2048)
    parser.add_argument("--waveforms", type=int, default=32)
    parser.add_argument(
        "--api",
        choices=("normal", "chunked", "both"),
        default="both",
    )
    parser.add_argument("--chunk-size", type=int, default=4)
    parser.add_argument("--timeout-ms", type=int, default=60000)
    parser.add_argument("--settle-ms", type=int, default=10)
    parser.add_argument(
        "--max-reported-failures",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--failure-output-dir",
        type=Path,
        default=Path("spybuffer_readout_inhibit_failures"),
        help=(
            "Base directory for timestamped failure artifacts. It is not "
            "created when the campaign passes."
        ),
    )
    parser.add_argument(
        "--max-artifact-failures",
        type=int,
        default=10000,
        help="Maximum detailed ramp failures written to CSV and available for plots.",
    )
    parser.add_argument(
        "--max-failure-plots",
        type=int,
        default=120,
        help="Global safety limit for annotated ramp-failure PNG files.",
    )
    parser.add_argument(
        "--plots-per-failing-channel",
        type=int,
        default=3,
        help="Maximum representative ramp-failure plots for each failing channel.",
    )
    parser.add_argument(
        "--plot-context-samples",
        type=int,
        default=16,
        help="Samples shown on each side of a failed transition in the detail panel.",
    )
    add_trigger_source_arguments(parser, default="software")
    parser.add_argument(
        "--hardware-trigger",
        action="store_true",
        dest="legacy_hardware_trigger",
        help="Deprecated alias for -trigger_source external.",
    )
    parser.add_argument(
        "--skip-ramp-configuration",
        action="store_true",
        help="Assume the ramp is already active and do not modify AFE registers.",
    )
    parser.add_argument(
        "--keep-ramp-enabled",
        action="store_true",
        help="Do not restore TEST_PATTERN_MODES and SYNC_PATTERN after the test.",
    )
    args = parser.parse_args()
    if args.legacy_hardware_trigger:
        if args.trigger_source is not None and args.trigger_source != "external":
            parser.error(
                "--hardware-trigger conflicts with "
                f"-trigger_source {args.trigger_source}"
            )
        args.trigger_source = "external"
        print(
            "warning: --hardware-trigger is deprecated; use "
            "-trigger_source external"
        )
    resolve_trigger_source(parser, args)

    try:
        channels = parse_channels(args.channels)
    except ValueError as error:
        parser.error(str(error))
    if args.samples < 2 or args.samples > 2048:
        parser.error("--samples must be in 2..2048")
    if args.waveforms < 1:
        parser.error("--waveforms must be greater than zero")
    if (
        args.api in ("chunked", "both")
        and (args.chunk_size < 1 or args.chunk_size > args.waveforms)
    ):
        parser.error("--chunk-size must be in 1..waveforms")
    if args.timeout_ms < 1:
        parser.error("--timeout-ms must be greater than zero")
    if args.settle_ms < 0:
        parser.error("--settle-ms cannot be negative")
    if (
        args.max_reported_failures is not None
        and args.max_reported_failures < 0
    ):
        parser.error("--max-reported-failures cannot be negative")
    if args.max_artifact_failures < 0:
        parser.error("--max-artifact-failures cannot be negative")
    if args.max_failure_plots < 0:
        parser.error("--max-failure-plots cannot be negative")
    if args.plots_per_failing_channel < 0:
        parser.error("--plots-per-failing-channel cannot be negative")
    if args.plot_context_samples < 1:
        parser.error("--plot-context-samples must be greater than zero")
    if args.skip_ramp_configuration and args.keep_ramp_enabled:
        parser.error(
            "--keep-ramp-enabled cannot be used with "
            "--skip-ramp-configuration"
        )

    endpoint = f"tcp://{args.ip}:{args.port}"
    print("DAPHNE spybuffer readout-inhibit ramp smoke test")
    print(f"  endpoint         : {endpoint}")
    print(f"  route            : {args.route}")
    print(f"  channels         : {channels}")
    print(f"  samples          : {args.samples}")
    print(f"  waveforms / API  : {args.waveforms} / {args.api}")
    print(f"  failure artifacts: {args.failure_output_dir} (created only on FAIL)")
    print(f"  trigger source   : {args.trigger_source}")

    context = zmq.Context()
    control_socket = make_socket(
        context,
        endpoint,
        args.timeout_ms,
        "spy-ramp-control",
    )
    acquisition_socket = make_socket(
        context,
        endpoint,
        args.timeout_ms,
        "spy-ramp-acquisition",
    )

    artifacts = FailureArtifactWriter(
        args.failure_output_dir,
        max_failure_records=args.max_artifact_failures,
        max_plots=args.max_failure_plots,
        plots_per_channel=args.plots_per_failing_channel,
        context_samples=args.plot_context_samples,
    )
    # Preserve the old hidden option for existing invocations while making
    # the artifact-specific limit the documented control.
    max_stored_failures = (
        args.max_artifact_failures
        if args.max_reported_failures is None
        else args.max_reported_failures
    )

    exit_code = 1
    ramp_configuration_attempted = False
    ramp_configuration_succeeded = False
    restore_errors: list[str] = []
    total_transitions = 0
    total_ramp_failures = 0
    total_timestamp_failures = 0
    tested_waveforms = 0
    overall_channel_failure_counts: Counter[int] = Counter()
    original_trigger_source = None
    try:
        def send_trigger_source_request(message_type: int, payload: bytes):
            reply = v2_request(
                control_socket,
                message_type,
                message_type + 1,
                payload,
                args.route,
            )
            return reply.type, reply.payload

        original_trigger_source = read_trigger_source(
            pb_high,
            send_trigger_source_request,
        )
        configure_trigger_source(
            pb_high,
            send_trigger_source_request,
            args.trigger_source,
        )
        print(
            f"[TRIGGER] configured {args.trigger_source} "
            f"(initially {original_trigger_source})"
        )

        if not args.skip_ramp_configuration:
            ramp_configuration_attempted = True
            configure_ramp(control_socket, args.route)
            ramp_configuration_succeeded = True
            time.sleep(args.settle_ms / 1000.0)
            if not args.software_trigger:
                prime_hardware_trigger_cursor(
                    acquisition_socket,
                    args.route,
                    channels[0],
                )

        stats: list[tuple[str, AcquisitionStats]] = []
        if args.api in ("normal", "both"):
            stats.append(
                (
                    "normal",
                    acquire_normal(
                        acquisition_socket,
                        args.route,
                        channels,
                        args.samples,
                        args.waveforms,
                        args.software_trigger,
                        max_stored_failures,
                        args.plots_per_failing_channel,
                        artifacts,
                    ),
                )
            )
        if args.api in ("chunked", "both"):
            stats.append(
                (
                    "chunked",
                    acquire_chunked(
                        acquisition_socket,
                        args.route,
                        channels,
                        args.samples,
                        args.waveforms,
                        args.chunk_size,
                        args.software_trigger,
                        max_stored_failures,
                        args.plots_per_failing_channel,
                        artifacts,
                    ),
                )
            )

        for label, api_stats in stats:
            tested_waveforms += len(api_stats.timestamps)
            total_transitions += api_stats.transitions
            total_ramp_failures += api_stats.ramp_failures
            overall_channel_failure_counts.update(
                dict(api_stats.channel_failure_counts)
            )
            report_channel_status(label, api_stats, channels)

            api_timestamp_failures = timestamp_failures(api_stats.timestamps)
            total_timestamp_failures += len(api_timestamp_failures)
            artifacts.record_timestamp_failures(
                label,
                api_stats.timestamps,
                api_timestamp_failures,
            )
            if api_timestamp_failures:
                timestamp_kinds = Counter(
                    failure.kind for failure in api_timestamp_failures
                )
                kind_summary = ", ".join(
                    f"{kind}={count}"
                    for kind, count in sorted(timestamp_kinds.items())
                )
                print(
                    f"[FAIL] {label} timestamps: "
                    f"{len(api_timestamp_failures)} failures "
                    f"({kind_summary})"
                )

        if total_ramp_failures == 0 and total_timestamp_failures == 0:
            print(
                f"[PASS] ramp smoke test: transitions={total_transitions}, "
                f"waveforms={tested_waveforms}"
            )
            exit_code = 0
        else:
            failed_channels = [
                channel
                for channel in channels
                if channel in overall_channel_failure_counts
            ]
            passed_channels = [
                channel
                for channel in channels
                if channel not in overall_channel_failure_counts
            ]
            print(
                f"[FAIL] ramp smoke test: "
                f"ramp_failures={total_ramp_failures}, "
                f"timestamp_failures={total_timestamp_failures}"
            )
            if failed_channels:
                print(
                    "[FAIL] campaign failed channels: "
                    + ", ".join(f"ch{channel}" for channel in failed_channels)
                )
                print(
                    f"[PASS] campaign clean channels "
                    f"({len(passed_channels)}/{len(channels)}): "
                    f"{format_channel_ranges(passed_channels)}"
                )
            print(
                "[INFO] Exact samples, deltas and representative plots are "
                "stored in the diagnostic artifact directory."
            )
    except KeyboardInterrupt:
        print("[FAIL] interrupted by user")
        artifacts.record_error("interrupted by user")
    except Exception as error:
        print(f"[FAIL] {error}")
        artifacts.record_error(str(error))
    finally:
        should_restore = ramp_configuration_attempted and (
            not args.keep_ramp_enabled or not ramp_configuration_succeeded
        )
        if should_restore:
            print("Restoring normal AFE output...")
            restore_errors = disable_ramp(control_socket, args.route)
            for error in restore_errors:
                print(f"[FAIL] ramp cleanup: {error}")
                artifacts.record_error(f"ramp cleanup: {error}")
            if restore_errors:
                exit_code = 1
        elif ramp_configuration_succeeded:
            print("[WARN] AFE ramp left enabled by request")

        if original_trigger_source is not None:
            try:
                configure_trigger_source(
                    pb_high,
                    send_trigger_source_request,
                    original_trigger_source,
                )
                print(
                    f"[RESTORE] trigger source: {original_trigger_source}"
                )
            except Exception as error:
                print(f"[FAIL] trigger-source cleanup: {error}")
                artifacts.record_error(f"trigger-source cleanup: {error}")
                exit_code = 1

        acquisition_socket.close(0)
        control_socket.close(0)
        context.term()

        if exit_code != 0:
            artifact_dir = artifacts.finalize(
                {
                    "result": "FAIL",
                    "endpoint": endpoint,
                    "route": args.route,
                    "channels": channels,
                    "samples": args.samples,
                    "requested_waveforms_per_api": args.waveforms,
                    "tested_waveforms": tested_waveforms,
                    "api": args.api,
                    "trigger_source": args.trigger_source,
                    "transitions": total_transitions,
                    "ramp_failures": total_ramp_failures,
                    "timestamp_failures": total_timestamp_failures,
                    "channel_failure_counts": dict(
                        sorted(overall_channel_failure_counts.items())
                    ),
                    "failed_channels": [
                        channel
                        for channel in channels
                        if channel in overall_channel_failure_counts
                    ],
                    "passed_channels": [
                        channel
                        for channel in channels
                        if channel not in overall_channel_failure_counts
                    ],
                }
            )
            if artifact_dir is not None:
                print(f"[INFO] detailed diagnostics: {artifact_dir}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
