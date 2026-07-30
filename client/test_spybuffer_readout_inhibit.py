#!/usr/bin/env python3
"""AFE-ramp smoke test for protected normal and chunked spybuffer readout."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import random
import sys
import time
import uuid

import zmq

from spybuffer_ramp_validation import RampValidationResult, validate_ramp_data


REPO_ROOT = Path(__file__).resolve().parents[1]
UINT64_MASK = (1 << 64) - 1
UINT64_HALF_RANGE = 1 << 63


def load_protobuf_modules():
    candidates: list[Path] = []
    if os.environ.get("DAPHNE_PROTO_PYTHON_DIR"):
        candidates.append(Path(os.environ["DAPHNE_PROTO_PYTHON_DIR"]))
    if os.environ.get("DAPHNE_BUILD_DIR"):
        candidates.append(
            Path(os.environ["DAPHNE_BUILD_DIR"]) / "srcs" / "protobuf"
        )
    for build_name in ("build-petalinux", "build-client", "build-test", "build"):
        candidates.append(REPO_ROOT / build_name / "srcs" / "protobuf")
    candidates.append(REPO_ROOT / "srcs" / "protobuf")

    visited: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in visited:
            continue
        visited.add(candidate)

        high_path = candidate / "daphneV3_high_level_confs_pb2.py"
        low_path = candidate / "daphneV3_low_level_confs_pb2.py"
        if not high_path.is_file() or not low_path.is_file():
            continue
        if b"timestamps" not in high_path.read_bytes():
            continue

        sys.path.insert(0, str(candidate))
        try:
            high = importlib.import_module("daphneV3_high_level_confs_pb2")
            low = importlib.import_module("daphneV3_low_level_confs_pb2")
        finally:
            sys.path.pop(0)

        if "timestamps" not in high.DumpSpyBuffersResponse.DESCRIPTOR.fields_by_name:
            continue
        return high, low

    raise RuntimeError(
        "Compatible Python protobuf bindings were not found. Rebuild the "
        "project or set DAPHNE_PROTO_PYTHON_DIR."
    )


pb_high, pb_low = load_protobuf_modules()


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


def report_ramp_result(
    label: str,
    result: RampValidationResult,
    *,
    waveform_offset: int = 0,
) -> None:
    if result.failure_count:
        waveforms = ", ".join(
            f"wf{waveform_offset + waveform}={count}"
            for waveform, count in result.waveform_failure_counts
        )
        channels = ", ".join(
            f"ch{channel}={count}"
            for channel, count in result.channel_failure_counts
        )
        deltas = ", ".join(
            f"{delta}({delta - (1 << 14):+d})={count}"
            if delta > (1 << 13)
            else f"{delta}={count}"
            for delta, count in result.delta_failure_counts
        )
        print(f"[FAIL] {label} failures by waveform: {waveforms}")
        print(f"[FAIL] {label} failures by channel: {channels}")
        print(f"[FAIL] {label} unexpected delta histogram: {deltas}")

    for failure in result.failures:
        print(
            f"[FAIL] {label} waveform={waveform_offset + failure.waveform} "
            f"channel={failure.channel} sample={failure.sample} "
            f"previous=0x{failure.previous:04X} "
            f"current=0x{failure.current:04X} delta={failure.delta}"
        )
    if result.failure_count > len(result.failures):
        print(
            f"[FAIL] {label}: "
            f"{result.failure_count - len(result.failures)} additional "
            "ramp discontinuities were not printed"
        )


@dataclass
class AcquisitionStats:
    timestamps: list[int]
    transitions: int
    ramp_failures: int


def acquire_normal(
    socket: zmq.Socket,
    route: str,
    channels: list[int],
    samples: int,
    waveforms: int,
    software_trigger: bool,
    max_reported_failures: int,
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
        max_reported_failures=max_reported_failures,
    )
    report_ramp_result("normal", result)
    return AcquisitionStats(
        timestamps=[int(value) for value in response.timestamps],
        transitions=result.transitions,
        ramp_failures=result.failure_count,
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
    max_reported_failures: int,
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
    reported_failures = 0

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
        remaining_reports = max(0, max_reported_failures - reported_failures)
        result = validate_ramp_data(
            chunk.data,
            chunk_waveforms,
            channels,
            samples,
            max_reported_failures=remaining_reports,
        )
        chunk_label = (
            f"chunked[{chunk.waveformStart}:"
            f"{chunk.waveformStart + chunk_waveforms}]"
        )
        report_ramp_result(
            chunk_label,
            result,
            waveform_offset=int(chunk.waveformStart),
        )
        reported_failures += len(result.failures)
        ramp_failures += result.failure_count
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
    )


def timestamp_failures(timestamps: list[int]) -> list[str]:
    failures: list[str] = []
    for index in range(1, len(timestamps)):
        previous = timestamps[index - 1]
        current = timestamps[index]
        delta = (current - previous) & UINT64_MASK
        if delta == 0:
            failures.append(
                f"duplicate timestamp at waveform {index}: "
                f"0x{current:016X}"
            )
        elif delta >= UINT64_HALF_RANGE:
            failures.append(
                f"non-monotonic timestamp at waveform {index}: "
                f"0x{previous:016X} -> 0x{current:016X}"
            )
    return failures


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
    parser.add_argument("--waveforms", type=int, default=4)
    parser.add_argument(
        "--api",
        choices=("normal", "chunked", "both"),
        default="both",
    )
    parser.add_argument("--chunk-size", type=int, default=2)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--settle-ms", type=int, default=10)
    parser.add_argument("--max-reported-failures", type=int, default=20)
    trigger_group = parser.add_mutually_exclusive_group()
    trigger_group.add_argument(
        "--software-trigger",
        dest="software_trigger",
        action="store_true",
        help="Issue one software trigger per waveform (default).",
    )
    trigger_group.add_argument(
        "--hardware-trigger",
        dest="software_trigger",
        action="store_false",
        help="Wait for external hardware triggers.",
    )
    parser.set_defaults(software_trigger=True)
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
    if args.max_reported_failures < 0:
        parser.error("--max-reported-failures cannot be negative")
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
    print(
        "  trigger          : "
        + ("software" if args.software_trigger else "hardware")
    )

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

    exit_code = 1
    ramp_configuration_attempted = False
    ramp_configuration_succeeded = False
    restore_errors: list[str] = []
    try:
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
                        args.max_reported_failures,
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
                        args.max_reported_failures,
                    ),
                )
            )

        all_timestamps: list[int] = []
        total_transitions = 0
        total_ramp_failures = 0
        for label, api_stats in stats:
            all_timestamps.extend(api_stats.timestamps)
            total_transitions += api_stats.transitions
            total_ramp_failures += api_stats.ramp_failures
            print(
                f"[{'PASS' if api_stats.ramp_failures == 0 else 'FAIL'}] "
                f"{label}: transitions={api_stats.transitions} "
                f"ramp_failures={api_stats.ramp_failures}"
            )

        ts_failures = timestamp_failures(all_timestamps)
        for failure in ts_failures:
            print(f"[FAIL] {failure}")

        if total_ramp_failures == 0 and not ts_failures:
            print(
                f"[PASS] ramp smoke test: transitions={total_transitions}, "
                f"waveforms={len(all_timestamps)}"
            )
            exit_code = 0
        else:
            print(
                f"[FAIL] ramp smoke test: "
                f"ramp_failures={total_ramp_failures}, "
                f"timestamp_failures={len(ts_failures)}"
            )
    except KeyboardInterrupt:
        print("[FAIL] interrupted by user")
    except Exception as error:
        print(f"[FAIL] {error}")
    finally:
        should_restore = ramp_configuration_attempted and (
            not args.keep_ramp_enabled or not ramp_configuration_succeeded
        )
        if should_restore:
            print("Restoring normal AFE output...")
            restore_errors = disable_ramp(control_socket, args.route)
            for error in restore_errors:
                print(f"[FAIL] ramp cleanup: {error}")
            if restore_errors:
                exit_code = 1
        elif ramp_configuration_succeeded:
            print("[WARN] AFE ramp left enabled by request")

        acquisition_socket.close(0)
        control_socket.close(0)
        context.term()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
