#!/usr/bin/env python3
"""Diagnose AFE serial bit placement and inter-word timing with test patterns."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
import random
import sys
import time
import uuid

import zmq

from afe_pattern_validation import (
    ADC_MASK,
    ChannelDiagnosis,
    PatternDefinition,
    PatternValidationResult,
    build_pattern_suite,
    diagnose_channels,
    validate_pattern_data,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
AFE_REGISTER_ADDRESSES = (2, 5, 10)


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
        descriptor = high_path.read_bytes()
        if (
            b"MT2_WRITE_AFE_FUNCTION_REQ" not in descriptor
            or b"MT2_DUMP_SPYBUFFER_REQ" not in descriptor
        ):
            continue

        sys.path.insert(0, str(candidate))
        try:
            high = importlib.import_module("daphneV3_high_level_confs_pb2")
            low = importlib.import_module("daphneV3_low_level_confs_pb2")
        finally:
            sys.path.pop(0)
        required = (
            "ControlEnvelopeV2",
            "DumpSpyBuffersRequest",
            "DumpSpyBuffersResponse",
        )
        if all(hasattr(high, name) for name in required):
            return high, low

    raise RuntimeError(
        "Compatible Python protobuf bindings were not found. Rebuild the "
        "protos or set DAPHNE_PROTO_PYTHON_DIR to their generated directory."
    )


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
                raise ValueError(f"descending channel range: {token}")
            channels.extend(range(first, last + 1))
        else:
            channels.append(int(token))
    channels = list(dict.fromkeys(channels))
    if not channels:
        raise ValueError("at least one channel is required")
    invalid = [channel for channel in channels if channel < 0 or channel > 39]
    if invalid:
        raise ValueError(f"channels outside 0..39: {invalid}")
    return channels


def format_ranges(values: list[int]) -> str:
    if not values:
        return "none"
    values = sorted(dict.fromkeys(values))
    ranges: list[str] = []
    first = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(first) if first == previous else f"{first}-{previous}")
        first = previous = value
    ranges.append(str(first) if first == previous else f"{first}-{previous}")
    return ",".join(ranges)


def next_ids() -> tuple[int, int]:
    now = time.time_ns()
    mask = (1 << 63) - 1
    return (
        ((now << 7) ^ random.getrandbits(31)) & mask,
        ((now << 1) ^ random.getrandbits(31)) & mask,
    )


class V2Client:
    def __init__(self, pb_high, pb_low, endpoint: str, route: str, timeout_ms: int):
        self.pb_high = pb_high
        self.pb_low = pb_low
        self.route = route
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(
            zmq.IDENTITY,
            f"afe-pattern-matrix-{uuid.uuid4()}".encode("ascii"),
        )
        self.socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self.socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
        self.socket.connect(endpoint)

    def close(self) -> None:
        self.socket.close(0)
        self.context.term()

    def request(self, request_type: int, response_type: int, payload: bytes):
        envelope = self.pb_high.ControlEnvelopeV2()
        envelope.version = 2
        envelope.dir = self.pb_high.DIR_REQUEST
        envelope.type = request_type
        envelope.payload = payload
        envelope.task_id, envelope.msg_id = next_ids()
        envelope.timestamp_ns = time.time_ns()
        envelope.route = self.route
        self.socket.send(envelope.SerializeToString())

        frames = [self.socket.recv()]
        while self.socket.getsockopt(zmq.RCVMORE):
            frames.append(self.socket.recv())
        reply = self.pb_high.ControlEnvelopeV2()
        if not reply.ParseFromString(frames[-1]):
            raise RuntimeError("Could not parse ControlEnvelopeV2 response")
        if reply.dir != self.pb_high.DIR_RESPONSE:
            raise RuntimeError(f"Unexpected response direction: {reply.dir}")
        if reply.correl_id != envelope.msg_id:
            raise RuntimeError(
                f"Correlation mismatch: {reply.correl_id} != {envelope.msg_id}"
            )
        if reply.type != response_type:
            raise RuntimeError(
                f"Unexpected response type {reply.type}; expected {response_type}"
            )
        return reply

    def set_afe_function(self, afe: int, function: str, value: int) -> None:
        request = self.pb_low.cmd_writeAFEFunction()
        request.afeBlock = afe
        request.function = function
        request.configValue = value
        reply = self.request(
            self.pb_high.MT2_WRITE_AFE_FUNCTION_REQ,
            self.pb_high.MT2_WRITE_AFE_FUNCTION_RESP,
            request.SerializeToString(),
        )
        response = self.pb_low.cmd_writeAFEFunction_response()
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

    def read_afe_register(self, afe: int, address: int) -> int:
        request = self.pb_low.cmd_readAFEReg()
        request.afeBlock = afe
        request.regAddress = address
        reply = self.request(
            self.pb_high.MT2_READ_AFE_REG_REQ,
            self.pb_high.MT2_READ_AFE_REG_RESP,
            request.SerializeToString(),
        )
        response = self.pb_low.cmd_readAFEReg_response()
        if not response.ParseFromString(reply.payload):
            raise RuntimeError("Could not parse cmd_readAFEReg_response")
        if not response.success:
            raise RuntimeError(
                f"AFE{afe} register {address} read failed: {response.message}"
            )
        if response.afeBlock != afe or response.regAddress != address:
            raise RuntimeError("AFE register read response metadata mismatch")
        return int(response.regValue) & 0xFFFF

    def write_afe_register(self, afe: int, address: int, value: int) -> None:
        request = self.pb_low.cmd_writeAFEReg()
        request.afeBlock = afe
        request.regAddress = address
        request.regValue = value
        reply = self.request(
            self.pb_high.MT2_WRITE_AFE_REG_REQ,
            self.pb_high.MT2_WRITE_AFE_REG_RESP,
            request.SerializeToString(),
        )
        response = self.pb_low.cmd_writeAFEReg_response()
        if not response.ParseFromString(reply.payload):
            raise RuntimeError("Could not parse cmd_writeAFEReg_response")
        if not response.success:
            raise RuntimeError(
                f"AFE{afe} register {address} restore failed: {response.message}"
            )
        if response.regValue != value:
            raise RuntimeError(
                f"AFE{afe} register {address} readback "
                f"0x{response.regValue:04X} != 0x{value:04X}"
            )

    def acquire(
        self,
        channels: list[int],
        samples: int,
        waveforms: int,
    ) -> tuple[list[int], list[int]]:
        request = self.pb_high.DumpSpyBuffersRequest()
        request.channelList.extend(channels)
        request.numberOfSamples = samples
        request.numberOfWaveforms = waveforms
        request.softwareTrigger = True
        reply = self.request(
            self.pb_high.MT2_DUMP_SPYBUFFER_REQ,
            self.pb_high.MT2_DUMP_SPYBUFFER_RESP,
            request.SerializeToString(),
        )
        response = self.pb_high.DumpSpyBuffersResponse()
        if not response.ParseFromString(reply.payload):
            raise RuntimeError("Could not parse DumpSpyBuffersResponse")
        if not response.success:
            raise RuntimeError(f"Server rejected acquisition: {response.message}")
        if list(response.channelList) != channels:
            raise RuntimeError("Acquisition channel list does not match request")
        if response.numberOfSamples != samples:
            raise RuntimeError("Acquisition sample count does not match request")
        if response.numberOfWaveforms != waveforms:
            raise RuntimeError("Acquisition waveform count does not match request")
        if not response.softwareTrigger:
            raise RuntimeError("Acquisition response did not use software trigger")
        expected_words = len(channels) * samples * waveforms
        if len(response.data) != expected_words:
            raise RuntimeError(
                f"Acquisition data size {len(response.data)} != {expected_words}"
            )
        if len(response.timestamps) != waveforms:
            raise RuntimeError("Acquisition timestamp count does not match request")
        return (
            [int(value) for value in response.data],
            [int(value) for value in response.timestamps],
        )


def save_register_state(
    client: V2Client,
    afes: list[int],
) -> dict[int, dict[int, int]]:
    state: dict[int, dict[int, int]] = {}
    for afe in afes:
        state[afe] = {}
        for address in AFE_REGISTER_ADDRESSES:
            state[afe][address] = client.read_afe_register(afe, address)
    return state


def restore_register_state(
    client: V2Client,
    state: dict[int, dict[int, int]],
) -> list[str]:
    errors: list[str] = []
    # Restore CUSTOM_PATTERN and SYNC_PATTERN first. Register 2, which contains
    # TEST_PATTERN_MODES, is restored last so the original output mode is the
    # final externally visible state.
    for afe in sorted(state):
        for address in (5, 10, 2):
            if address not in state[afe]:
                continue
            try:
                client.write_afe_register(afe, address, state[afe][address])
            except Exception as error:
                errors.append(f"AFE{afe} register {address}: {error}")
    return errors


def apply_pattern(
    client: V2Client,
    afes: list[int],
    pattern: PatternDefinition,
) -> None:
    if pattern.custom_value is not None:
        for afe in afes:
            client.set_afe_function(
                afe,
                "CUSTOM_PATTERN",
                pattern.custom_value,
            )
    for afe in afes:
        client.set_afe_function(afe, "TEST_PATTERN_MODES", pattern.mode)


def format_bits(bits: tuple[int, ...]) -> str:
    return "none" if not bits else ",".join(f"D{bit}" for bit in bits)


def report_pattern(
    index: int,
    count: int,
    result: PatternValidationResult,
    max_console_failures: int,
) -> None:
    pattern = result.pattern
    expected = (
        "alternating 0x0000/0x3FFF"
        if pattern.behavior == "toggle"
        else f"0x{int(pattern.expected_code):04X}"
    )
    failed = [entry for entry in result.channel_results if not entry.ok]
    prefix = "PASS" if not failed else "FAIL"
    print(
        f"[{prefix}] {index:02d}/{count:02d} {pattern.name}: "
        f"expected={expected}; checks={result.checks}; "
        f"failures={result.failure_count}"
    )
    if not failed:
        return
    print(
        "       failed channels: "
        + format_ranges([entry.channel for entry in failed])
    )
    for entry in failed[:max_console_failures]:
        detail = (
            f"dominant=0x{entry.dominant_code:04X} "
            f"({entry.dominant_count}/{result.waveform_count * result.samples_per_waveform}), "
            f"wrong_codes={entry.value_failures}, "
            f"bad_transitions={entry.transition_failures}"
        )
        if entry.failing_bits:
            detail += f", affected_bits={format_bits(entry.failing_bits)}"
        print(f"       ch{entry.channel}: {detail}")
    omitted = len(failed) - max_console_failures
    if omitted > 0:
        print(f"       ... {omitted} additional failing channels in output files")


def _pattern_result_dict(result: PatternValidationResult) -> dict:
    return {
        "pattern": asdict(result.pattern),
        "waveform_count": result.waveform_count,
        "samples_per_waveform": result.samples_per_waveform,
        "checks": result.checks,
        "failure_count": result.failure_count,
        "channel_results": [
            {
                **asdict(channel_result),
                "dominant_code_hex": f"0x{channel_result.dominant_code:04X}",
                "observed_code_counts": [
                    {"code": code, "code_hex": f"0x{code:04X}", "count": count}
                    for code, count in channel_result.observed_code_counts
                ],
            }
            for channel_result in result.channel_results
        ],
    }


def write_results(
    run_dir: Path,
    args,
    channels: list[int],
    afes: list[int],
    register_state: dict[int, dict[int, int]],
    results: list[PatternValidationResult],
    timestamps: dict[str, list[int]],
    diagnoses: tuple[ChannelDiagnosis, ...],
    restore_errors: list[str],
    run_error: str | None,
) -> None:
    with (run_dir / "pattern_results.csv").open(
        "w", newline="", encoding="utf-8"
    ) as output:
        writer = csv.DictWriter(
            output,
            fieldnames=(
                "pattern",
                "category",
                "mode",
                "expected",
                "channel",
                "checks",
                "failures",
                "value_failures",
                "transition_failures",
                "dominant_observed",
                "dominant_count",
                "unique_codes",
                "affected_bits",
                "false_positive_bits",
                "false_negative_bits",
                "top_observed_codes",
                "status",
            ),
        )
        writer.writeheader()
        for result in results:
            for channel_result in result.channel_results:
                writer.writerow(
                    {
                        "pattern": result.pattern.name,
                        "category": result.pattern.category,
                        "mode": result.pattern.mode,
                        "expected": (
                            "toggle"
                            if result.pattern.expected_code is None
                            else f"0x{result.pattern.expected_code:04X}"
                        ),
                        "channel": channel_result.channel,
                        "checks": channel_result.checks,
                        "failures": channel_result.failure_count,
                        "value_failures": channel_result.value_failures,
                        "transition_failures": channel_result.transition_failures,
                        "dominant_observed": f"0x{channel_result.dominant_code:04X}",
                        "dominant_count": channel_result.dominant_count,
                        "unique_codes": channel_result.unique_code_count,
                        "affected_bits": format_bits(channel_result.failing_bits),
                        "false_positive_bits": ";".join(
                            f"D{bit}:{count}"
                            for bit, count in channel_result.false_positive_bits
                        ),
                        "false_negative_bits": ";".join(
                            f"D{bit}:{count}"
                            for bit, count in channel_result.false_negative_bits
                        ),
                        "top_observed_codes": ";".join(
                            f"0x{code:04X}:{count}"
                            for code, count in channel_result.observed_code_counts
                        ),
                        "status": "PASS" if channel_result.ok else "FAIL",
                    }
                )

    with (run_dir / "failure_examples.csv").open(
        "w", newline="", encoding="utf-8"
    ) as output:
        writer = csv.DictWriter(
            output,
            fieldnames=(
                "pattern",
                "channel",
                "waveform",
                "sample",
                "kind",
                "previous",
                "current",
                "expected",
            ),
        )
        writer.writeheader()
        for result in results:
            for channel_result in result.channel_results:
                for example in channel_result.examples:
                    writer.writerow(
                        {
                            "pattern": result.pattern.name,
                            "channel": example.channel,
                            "waveform": example.waveform,
                            "sample": example.sample,
                            "kind": example.kind,
                            "previous": (
                                "" if example.previous is None else f"0x{example.previous:04X}"
                            ),
                            "current": f"0x{example.current:04X}",
                            "expected": (
                                "" if example.expected is None else f"0x{example.expected:04X}"
                            ),
                        }
                    )

    with (run_dir / "channel_diagnosis.csv").open(
        "w", newline="", encoding="utf-8"
    ) as output:
        writer = csv.DictWriter(
            output,
            fieldnames=(
                "channel",
                "status",
                "classification",
                "custom_failures",
                "builtin_failures",
                "temporal_failures",
                "affected_bits",
                "walking_one_response",
                "interpretation",
            ),
        )
        writer.writeheader()
        for diagnosis in diagnoses:
            writer.writerow(
                {
                    "channel": diagnosis.channel,
                    "status": diagnosis.status,
                    "classification": diagnosis.classification,
                    "custom_failures": diagnosis.custom_failures,
                    "builtin_failures": diagnosis.builtin_failures,
                    "temporal_failures": diagnosis.temporal_failures,
                    "affected_bits": format_bits(diagnosis.failing_bits),
                    "walking_one_response": "; ".join(diagnosis.bit_response),
                    "interpretation": diagnosis.interpretation,
                }
            )

    failed_channels = [diagnosis.channel for diagnosis in diagnoses if not diagnosis.ok]
    summary = {
        "result": (
            "ERROR"
            if run_error or restore_errors or len(results) != len(build_pattern_suite())
            else ("FAIL" if failed_channels else "PASS")
        ),
        "endpoint": f"tcp://{args.ip}:{args.port}",
        "route": args.route,
        "channels": channels,
        "afes": afes,
        "samples": args.samples,
        "waveforms_per_pattern": args.waveforms,
        "settle_ms": args.settle_ms,
        "patterns_completed": len(results),
        "patterns_expected": len(build_pattern_suite()),
        "original_registers": {
            str(afe): {
                str(address): value
                for address, value in sorted(registers.items())
            }
            for afe, registers in sorted(register_state.items())
        },
        "timestamps": timestamps,
        "failed_channels": failed_channels,
        "passed_channels": [
            diagnosis.channel for diagnosis in diagnoses if diagnosis.ok
        ],
        "channel_diagnoses": [asdict(diagnosis) for diagnosis in diagnoses],
        "pattern_results": [_pattern_result_dict(result) for result in results],
        "restore_errors": restore_errors,
        "error": run_error,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def report_diagnoses(
    diagnoses: tuple[ChannelDiagnosis, ...],
    channels: list[int],
) -> bool:
    failed = [diagnosis for diagnosis in diagnoses if not diagnosis.ok]
    passed = [diagnosis.channel for diagnosis in diagnoses if diagnosis.ok]
    print("\nChannel diagnosis")
    if not failed:
        print(
            f"[PASS] all {len(channels)} channels preserve every static bit "
            "and every toggle transition"
        )
        return True

    for diagnosis in failed:
        print(
            f"[FAIL] ch{diagnosis.channel}: {diagnosis.classification}; "
            f"affected_bits={format_bits(diagnosis.failing_bits)}"
        )
        if diagnosis.bit_response:
            print("       walking-one: " + "; ".join(diagnosis.bit_response))
        print("       interpretation: " + diagnosis.interpretation)
    print(
        f"[PASS] clean channels ({len(passed)}/{len(channels)}): "
        f"{format_ranges(passed)}"
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply the AFE5808A fixed, walking-bit, and toggle patterns; "
            "then classify each channel as a static bit-path, temporal "
            "word-boundary, built-in-pattern, or clean result."
        )
    )
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--route", default="mezz/0")
    parser.add_argument("--channels", default="0-39")
    parser.add_argument("--samples", type=int, default=256)
    parser.add_argument("--waveforms", type=int, default=8)
    parser.add_argument("--settle-ms", type=int, default=10)
    parser.add_argument("--timeout-ms", type=int, default=120000)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("afe_pattern_test_results"),
    )
    parser.add_argument("--max-examples-per-channel", type=int, default=4)
    parser.add_argument("--max-console-failures", type=int, default=8)
    args = parser.parse_args()

    try:
        channels = parse_channels(args.channels)
    except ValueError as error:
        parser.error(str(error))
    if args.samples < 2 or args.samples > 2048:
        parser.error("--samples must be in 2..2048")
    if args.waveforms < 1:
        parser.error("--waveforms must be greater than zero")
    if args.settle_ms < 0:
        parser.error("--settle-ms cannot be negative")
    if args.timeout_ms < 1:
        parser.error("--timeout-ms must be greater than zero")
    if args.max_examples_per_channel < 0:
        parser.error("--max-examples-per-channel cannot be negative")
    if args.max_console_failures < 1:
        parser.error("--max-console-failures must be greater than zero")

    afes = sorted({channel // 8 for channel in channels})
    patterns = build_pattern_suite()
    endpoint = f"tcp://{args.ip}:{args.port}"
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = args.output_dir / f"{timestamp}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)

    print("DAPHNE AFE test-pattern matrix")
    print(f"  endpoint          : {endpoint}")
    print(f"  route             : {args.route}")
    print(f"  channels          : {channels}")
    print(f"  affected AFEs     : {afes}")
    print(f"  patterns          : {len(patterns)}")
    print(f"  samples/waveforms : {args.samples} / {args.waveforms}")
    print("  trigger           : software")
    print(f"  detailed output   : {run_dir}")
    print(
        "[INFO] PASS requires exact static codes and strict 0x0000/0x3FFF "
        "alternation on every requested channel."
    )

    client: V2Client | None = None
    register_state: dict[int, dict[int, int]] = {}
    results: list[PatternValidationResult] = []
    timestamps: dict[str, list[int]] = {}
    restore_errors: list[str] = []
    run_error: str | None = None
    interrupted = False
    try:
        pb_high, pb_low = load_protobuf_modules()
        client = V2Client(pb_high, pb_low, endpoint, args.route, args.timeout_ms)
        register_state = save_register_state(client, afes)
        print("[INFO] saved AFE registers 2, 5 and 10 for exact restoration")

        for afe in afes:
            client.set_afe_function(afe, "SYNC_PATTERN", 1)

        for index, pattern in enumerate(patterns, start=1):
            apply_pattern(client, afes, pattern)
            time.sleep(args.settle_ms / 1000.0)
            data, pattern_timestamps = client.acquire(
                channels,
                args.samples,
                args.waveforms,
            )
            result = validate_pattern_data(
                pattern,
                data,
                args.waveforms,
                channels,
                args.samples,
                max_examples_per_channel=args.max_examples_per_channel,
            )
            results.append(result)
            timestamps[pattern.name] = pattern_timestamps
            report_pattern(
                index,
                len(patterns),
                result,
                args.max_console_failures,
            )
    except KeyboardInterrupt:
        interrupted = True
        run_error = "interrupted by user"
        print("[FAIL] interrupted by user")
    except Exception as error:
        run_error = str(error)
        print(f"[FAIL] {error}")
    finally:
        if client is not None:
            if register_state:
                print("Restoring original AFE registers...")
                restore_errors = restore_register_state(client, register_state)
                for error in restore_errors:
                    print(f"[FAIL] restore: {error}")
            client.close()

    complete = len(results) == len(patterns) and run_error is None
    diagnoses = (
        diagnose_channels(results, channels)
        if complete
        else tuple()
    )
    if diagnoses:
        passed = report_diagnoses(diagnoses, channels)
    else:
        passed = False
        print(
            "[INFO] channel classification is unavailable because the "
            "pattern matrix did not complete"
        )
    write_results(
        run_dir,
        args,
        channels,
        afes,
        register_state,
        results,
        timestamps,
        diagnoses,
        restore_errors,
        run_error,
    )
    print(f"[INFO] detailed diagnostics: {run_dir}")

    if interrupted:
        return 130
    if run_error or restore_errors or len(results) != len(patterns):
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
