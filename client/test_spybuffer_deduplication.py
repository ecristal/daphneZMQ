#!/usr/bin/env python3
"""Continuous hardware-trigger spybuffer timestamp/rate verification client."""

from __future__ import annotations

import argparse
from array import array
from collections import deque
import hashlib
import importlib
import math
import os
from pathlib import Path
import random
import sys
import time
import uuid

import zmq


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_protobuf_module():
    candidates: list[Path] = []
    if os.environ.get("DAPHNE_PROTO_PYTHON_DIR"):
        candidates.append(Path(os.environ["DAPHNE_PROTO_PYTHON_DIR"]))
    if os.environ.get("DAPHNE_BUILD_DIR"):
        candidates.append(Path(os.environ["DAPHNE_BUILD_DIR"]) / "srcs" / "protobuf")
    for build_name in (
        "build-petalinux",
        "build-client",
        "build-test",
        "build",
    ):
        candidates.append(REPO_ROOT / build_name / "srcs" / "protobuf")
    candidates.append(REPO_ROOT / "srcs" / "protobuf")

    stale_binding_found = False
    for candidate in candidates:
        if not (candidate / "daphneV3_high_level_confs_pb2.py").is_file():
            continue
        sys.path.insert(0, str(candidate))
        try:
            module = importlib.import_module("daphneV3_high_level_confs_pb2")
            if "timestamps" in module.DumpSpyBuffersResponse.DESCRIPTOR.fields_by_name:
                return module
            stale_binding_found = True
        finally:
            sys.path.pop(0)
        sys.modules.pop("daphneV3_high_level_confs_pb2", None)
        sys.modules.pop("daphneV3_low_level_confs_pb2", None)

    detail = "found only stale bindings" if stale_binding_found else "found no bindings"
    raise RuntimeError(
        "Python protobuf bindings with spybuffer timestamps are required; "
        f"{detail}. Rebuild the project or set DAPHNE_PROTO_PYTHON_DIR."
    )


pb = load_protobuf_module()


UINT64_MASK = (1 << 64) - 1
UINT64_HALF_RANGE = 1 << 63


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
                raise ValueError(f"Invalid descending channel range: {token}")
            channels.extend(range(first, last + 1))
        else:
            channels.append(int(token))

    unique = list(dict.fromkeys(channels))
    if not unique:
        raise ValueError("At least one channel is required")
    invalid = [channel for channel in unique if channel < 0 or channel > 39]
    if invalid:
        raise ValueError(f"Channels outside 0..39: {invalid}")
    return unique


def make_socket(
    context: zmq.Context,
    endpoint: str,
    timeout_ms: int,
    generation: int,
) -> zmq.Socket:
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    identity = f"spy-dedup-{uuid.uuid4()}-{generation}".encode("ascii")
    socket.setsockopt(zmq.IDENTITY, identity)
    socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
    socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
    socket.connect(endpoint)
    return socket


def next_ids() -> tuple[int, int]:
    now = time.time_ns()
    mask = (1 << 63) - 1
    task_id = ((now << 7) ^ random.getrandbits(31)) & mask
    msg_id = ((now << 1) ^ random.getrandbits(31)) & mask
    return task_id, msg_id


def request_waveform(
    socket: zmq.Socket,
    channels: list[int],
    samples: int,
    route: str,
    software_trigger: bool,
) -> tuple[int, bytes]:
    request = pb.DumpSpyBuffersRequest()
    request.channelList.extend(channels)
    request.numberOfSamples = samples
    request.numberOfWaveforms = 1
    request.softwareTrigger = software_trigger

    envelope = pb.ControlEnvelopeV2()
    envelope.version = 2
    envelope.dir = pb.DIR_REQUEST
    envelope.type = pb.MT2_DUMP_SPYBUFFER_REQ
    envelope.payload = request.SerializeToString()
    envelope.task_id, envelope.msg_id = next_ids()
    envelope.timestamp_ns = time.time_ns()
    envelope.route = route

    socket.send(envelope.SerializeToString())
    frames = [socket.recv()]
    while socket.getsockopt(zmq.RCVMORE):
        frames.append(socket.recv())

    reply_envelope = pb.ControlEnvelopeV2()
    if not reply_envelope.ParseFromString(frames[-1]):
        raise RuntimeError("Could not parse ControlEnvelopeV2 response")
    if reply_envelope.dir != pb.DIR_RESPONSE:
        raise RuntimeError(f"Unexpected response direction: {reply_envelope.dir}")
    if reply_envelope.type != pb.MT2_DUMP_SPYBUFFER_RESP:
        raise RuntimeError(f"Unexpected response type: {reply_envelope.type}")
    if reply_envelope.correl_id != envelope.msg_id:
        raise RuntimeError(
            f"Correlation mismatch: {reply_envelope.correl_id} != {envelope.msg_id}"
        )

    response = pb.DumpSpyBuffersResponse()
    if not response.ParseFromString(reply_envelope.payload):
        raise RuntimeError("Could not parse DumpSpyBuffersResponse")
    if not response.success:
        raise RuntimeError(f"Server rejected acquisition: {response.message}")
    if len(response.timestamps) != 1:
        raise RuntimeError(
            "Expected exactly one FPGA timestamp; rebuild server and Python "
            f"protobuf bindings (received {len(response.timestamps)})"
        )

    expected_words = len(channels) * samples
    if len(response.data) != expected_words:
        raise RuntimeError(
            f"Waveform size mismatch: {len(response.data)} != {expected_words}"
        )

    waveform_bytes = array("I", response.data).tobytes()
    waveform_hash = hashlib.blake2b(waveform_bytes, digest_size=8).digest()
    return int(response.timestamps[0]), waveform_hash


def rate_from_host_times(host_times: deque[float]) -> float | None:
    if len(host_times) < 2:
        return None
    elapsed = host_times[-1] - host_times[0]
    return (len(host_times) - 1) / elapsed if elapsed > 0 else None


def rate_from_timestamp_deltas(
    timestamp_deltas: deque[int], timestamp_clock_hz: float
) -> float | None:
    if not timestamp_deltas:
        return None
    total_ticks = sum(timestamp_deltas)
    return (
        timestamp_clock_hz * len(timestamp_deltas) / total_ticks
        if total_ticks > 0
        else None
    )


def format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6g} Hz"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run indefinitely and verify that every server waveform has a new "
            "FPGA timestamp at the configured hardware-trigger rate."
        )
    )
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--route", default="mezz/0")
    parser.add_argument("--channels", default="0", help="Example: 0,1,8-15")
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument(
        "--expected-rate-hz",
        type=float,
        required=True,
        help="Trigger rate configured in the external signal generator.",
    )
    parser.add_argument(
        "--timestamp-clock-hz",
        type=float,
        default=62_500_000.0,
        help="FPGA timestamp tick frequency (default: 62.5 MHz).",
    )
    parser.add_argument(
        "--tolerance-percent",
        type=float,
        default=10.0,
        help="Allowed rolling rate error relative to the generator (default: 10%%).",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=100,
        help="Number of recent trigger intervals used for rolling rates.",
    )
    parser.add_argument(
        "--report-period-s",
        type=float,
        default=5.0,
        help="Periodic status interval (default: 5 s).",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=0,
        help="Socket timeout; 0 selects five expected trigger periods, minimum 5 s.",
    )
    parser.add_argument(
        "--software-trigger",
        action="store_true",
        help="Diagnostic mode: issue software triggers instead of using the generator.",
    )
    parser.add_argument(
        "--max-waveforms",
        type=int,
        default=0,
        help="Stop after this many waveforms; 0 keeps the test running indefinitely.",
    )
    args = parser.parse_args()

    if args.expected_rate_hz <= 0:
        parser.error("--expected-rate-hz must be greater than zero")
    if args.timestamp_clock_hz <= 0:
        parser.error("--timestamp-clock-hz must be greater than zero")
    if args.samples < 1 or args.samples > 2048:
        parser.error("--samples must be in 1..2048")
    if args.window < 2:
        parser.error("--window must be at least 2")
    if args.report_period_s <= 0:
        parser.error("--report-period-s must be greater than zero")
    if args.tolerance_percent < 0:
        parser.error("--tolerance-percent cannot be negative")
    if args.max_waveforms < 0:
        parser.error("--max-waveforms cannot be negative")

    try:
        channels = parse_channels(args.channels)
    except ValueError as error:
        parser.error(str(error))

    timeout_ms = args.timeout_ms
    if timeout_ms <= 0:
        timeout_ms = max(5000, math.ceil(5000.0 / args.expected_rate_hz))

    endpoint = f"tcp://{args.ip}:{args.port}"
    tolerance_fraction = args.tolerance_percent / 100.0
    expected_ticks = args.timestamp_clock_hz / args.expected_rate_hz

    print("DAPHNE continuous spybuffer deduplication test")
    print(f"  endpoint             : {endpoint}")
    print(f"  route                : {args.route}")
    print(f"  channels / samples   : {channels} / {args.samples}")
    print(f"  expected trigger rate: {args.expected_rate_hz:.9g} Hz")
    print(f"  timestamp clock      : {args.timestamp_clock_hz:.9g} Hz")
    print(f"  expected delta       : {expected_ticks:.3f} ticks")
    print(f"  tolerance            : +/-{args.tolerance_percent:.3g}%")
    print(f"  socket timeout       : {timeout_ms} ms")
    print("  duration             : indefinite; stop with Ctrl+C\n")

    context = zmq.Context()
    socket_generation = 0
    socket = make_socket(context, endpoint, timeout_ms, socket_generation)

    host_times: deque[float] = deque(maxlen=args.window + 1)
    timestamp_deltas: deque[int] = deque(maxlen=args.window)
    previous_timestamp: int | None = None
    previous_waveform_hash: bytes | None = None
    received = 0
    duplicate_timestamps = 0
    nonmonotonic_timestamps = 0
    rate_outliers = 0
    identical_payloads = 0
    timeouts = 0
    request_errors = 0
    last_report = time.monotonic()

    try:
        while True:
            try:
                timestamp, waveform_hash = request_waveform(
                    socket,
                    channels,
                    args.samples,
                    args.route,
                    args.software_trigger,
                )
            except zmq.Again:
                timeouts += 1
                print(
                    f"[TIMEOUT] no waveform in {timeout_ms} ms; "
                    "check generator and server trigger timeout"
                )
                socket.close(0)
                socket_generation += 1
                socket = make_socket(
                    context, endpoint, timeout_ms, socket_generation
                )
                continue
            except Exception as error:
                request_errors += 1
                print(f"[ERROR] {error}")
                time.sleep(min(1.0, 1.0 / args.expected_rate_hz))
                continue

            now = time.monotonic()
            received += 1
            host_times.append(now)

            if previous_waveform_hash == waveform_hash:
                identical_payloads += 1
            previous_waveform_hash = waveform_hash

            if previous_timestamp is not None:
                delta = (timestamp - previous_timestamp) & UINT64_MASK
                if delta == 0:
                    duplicate_timestamps += 1
                    print(
                        f"[FAIL] duplicate timestamp 0x{timestamp:016X} "
                        f"at waveform {received}"
                    )
                elif delta >= UINT64_HALF_RANGE:
                    nonmonotonic_timestamps += 1
                    print(
                        f"[FAIL] non-monotonic timestamp "
                        f"0x{previous_timestamp:016X} -> 0x{timestamp:016X}"
                    )
                else:
                    timestamp_deltas.append(delta)
                    instantaneous_rate = args.timestamp_clock_hz / delta
                    relative_error = abs(
                        instantaneous_rate - args.expected_rate_hz
                    ) / args.expected_rate_hz
                    if relative_error > tolerance_fraction:
                        rate_outliers += 1

            previous_timestamp = timestamp

            if now - last_report >= args.report_period_s:
                fpga_rate = rate_from_timestamp_deltas(
                    timestamp_deltas, args.timestamp_clock_hz
                )
                host_rate = rate_from_host_times(host_times)
                rate_error = (
                    abs(fpga_rate - args.expected_rate_hz)
                    / args.expected_rate_hz
                    if fpga_rate is not None
                    else None
                )
                status = (
                    "FAIL"
                    if duplicate_timestamps or nonmonotonic_timestamps
                    else "PASS"
                    if rate_error is not None and rate_error <= tolerance_fraction
                    else "WARN"
                )
                error_text = (
                    "n/a"
                    if rate_error is None
                    else f"{100.0 * rate_error:.3f}%"
                )
                print(
                    f"[{status}] n={received} ts=0x{timestamp:016X} "
                    f"fpga={format_rate(fpga_rate)} "
                    f"host={format_rate(host_rate)} target={args.expected_rate_hz:.6g} Hz "
                    f"error={error_text} dup_ts={duplicate_timestamps} "
                    f"nonmono={nonmonotonic_timestamps} "
                    f"rate_outliers={rate_outliers} same_data={identical_payloads} "
                    f"timeouts={timeouts} errors={request_errors}"
                )
                last_report = now

            if args.max_waveforms and received >= args.max_waveforms:
                break
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        socket.close(0)
        context.term()

    print(
        f"Final: received={received}, duplicate_timestamps={duplicate_timestamps}, "
        f"nonmonotonic_timestamps={nonmonotonic_timestamps}, "
        f"rate_outliers={rate_outliers}, identical_payloads={identical_payloads}, "
        f"timeouts={timeouts}, errors={request_errors}"
    )
    return 1 if duplicate_timestamps or nonmonotonic_timestamps else 0


if __name__ == "__main__":
    raise SystemExit(main())
