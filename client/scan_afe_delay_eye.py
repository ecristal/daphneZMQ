#!/usr/bin/env python3
"""Sweep AFE input delay using the synchronized AFE5808A ramp."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import importlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import uuid

import zmq

from afe_delay_sweep_analysis import TapWindow, summarize_afe_eye


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_protobuf_module():
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
        module_path = candidate / "daphneV3_high_level_confs_pb2.py"
        if not module_path.is_file():
            continue
        # protoc versions encode message names differently inside the
        # serialized descriptor, while enum names remain plain ASCII.
        if b"MT2_AFE_DELAY_SWEEP_REQ" not in module_path.read_bytes():
            continue

        sys.path.insert(0, str(candidate))
        try:
            module = importlib.import_module("daphneV3_high_level_confs_pb2")
        finally:
            sys.path.pop(0)
        if hasattr(module, "AfeDelaySweepRequest"):
            return module

    raise RuntimeError(
        "Python protobuf bindings with AfeDelaySweepRequest were not found. "
        "Rebuild the protos or set DAPHNE_PROTO_PYTHON_DIR to the generated "
        "binding directory."
    )


def parse_indices(spec: str, *, maximum: int) -> list[int]:
    values: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            first_text, last_text = token.split("-", 1)
            first, last = int(first_text), int(last_text)
            if last < first:
                raise ValueError(f"descending range: {token}")
            values.extend(range(first, last + 1))
        else:
            values.append(int(token))
    values = list(dict.fromkeys(values))
    if not values:
        raise ValueError("at least one AFE is required")
    invalid = [value for value in values if value < 0 or value > maximum]
    if invalid:
        raise ValueError(f"AFE indices outside 0..{maximum}: {invalid}")
    return values


def next_ids() -> tuple[int, int]:
    now = time.time_ns()
    mask = (1 << 63) - 1
    return (
        ((now << 7) ^ random.getrandbits(31)) & mask,
        ((now << 1) ^ random.getrandbits(31)) & mask,
    )


def run_sweep(pb, args, afes: list[int]):
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(
        zmq.IDENTITY, f"afe-delay-sweep-{uuid.uuid4()}".encode("ascii")
    )
    socket.setsockopt(zmq.RCVTIMEO, args.timeout_ms)
    socket.setsockopt(zmq.SNDTIMEO, args.timeout_ms)
    socket.connect(f"tcp://{args.ip}:{args.port}")

    request = pb.AfeDelaySweepRequest()
    request.afes.extend(afes)
    request.firstTap = args.first_tap
    request.lastTap = args.last_tap
    request.tapStep = args.tap_step
    request.numberOfSamples = args.samples
    request.numberOfWaveforms = args.waveforms
    request.settleTimeUs = args.settle_us

    envelope = pb.ControlEnvelopeV2()
    envelope.version = 2
    envelope.dir = pb.DIR_REQUEST
    envelope.type = pb.MT2_AFE_DELAY_SWEEP_REQ
    envelope.payload = request.SerializeToString()
    envelope.task_id, envelope.msg_id = next_ids()
    envelope.route = args.route
    envelope.timestamp_ns = time.time_ns()

    try:
        socket.send(envelope.SerializeToString())
        frames = [socket.recv()]
        while socket.getsockopt(zmq.RCVMORE):
            frames.append(socket.recv())
    finally:
        socket.close(0)
        context.term()

    reply_envelope = pb.ControlEnvelopeV2()
    if not reply_envelope.ParseFromString(frames[-1]):
        raise RuntimeError("server returned an invalid V2 envelope")
    if reply_envelope.dir != pb.DIR_RESPONSE:
        raise RuntimeError("server reply is not a V2 response")
    if reply_envelope.correl_id != envelope.msg_id:
        raise RuntimeError("server reply correlation ID does not match request")
    if reply_envelope.type != pb.MT2_AFE_DELAY_SWEEP_RESP:
        raise RuntimeError(
            f"unexpected response type {reply_envelope.type}; "
            f"expected {pb.MT2_AFE_DELAY_SWEEP_RESP}"
        )

    response = pb.AfeDelaySweepResponse()
    if not response.ParseFromString(reply_envelope.payload):
        raise RuntimeError("server returned an invalid AfeDelaySweepResponse")
    return response


def format_window(window: TapWindow | None) -> str:
    if window is None:
        return "none"
    return (
        f"{window.first_tap}..{window.last_tap} "
        f"({window.point_count} tested points, midpoint={window.recommended_tap})"
    )


def plot_heatmap(
    run_dir: Path,
    afe: int,
    taps: list[int],
    failure_matrix: list[list[int]],
    common_window: TapWindow | None,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    values = [
        [math.log10(failures + 1) for failures in channel]
        for channel in failure_matrix
    ]
    figure, axis = plt.subplots(figsize=(12, 5.5))
    image = axis.imshow(
        values,
        aspect="auto",
        origin="lower",
        interpolation="nearest",
        cmap="magma",
    )
    tick_count = min(12, len(taps))
    tick_indices = sorted(
        {round(index * (len(taps) - 1) / max(1, tick_count - 1))
         for index in range(tick_count)}
    )
    axis.set_xticks(tick_indices)
    axis.set_xticklabels([str(taps[index]) for index in tick_indices])
    axis.set_yticks(range(8))
    axis.set_yticklabels([f"ch{afe * 8 + lane}" for lane in range(8)])
    axis.set_xlabel("IDELAY tap")
    axis.set_ylabel("Board channel")
    axis.set_title(f"AFE{afe} ramp failures across input delay")
    colorbar = figure.colorbar(image, ax=axis)
    colorbar.set_label("log10(ramp failures + 1)")

    if common_window is not None:
        first_index = taps.index(common_window.first_tap)
        last_index = taps.index(common_window.last_tap)
        axis.axvspan(
            first_index - 0.5,
            last_index + 0.5,
            facecolor="none",
            edgecolor="cyan",
            linewidth=2,
            label="common passing window",
        )
        axis.axvline(
            taps.index(common_window.recommended_tap),
            color="cyan",
            linestyle="--",
            linewidth=1.5,
            label="recommended midpoint",
        )
        axis.legend(loc="upper right")

    figure.tight_layout()
    output = run_dir / f"afe{afe}_delay_eye.png"
    figure.savefig(output, dpi=160)
    plt.close(figure)
    return output


def save_results(response, args, requested_afes: list[int]) -> tuple[Path, bool]:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = args.output_dir / f"{timestamp}_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)

    csv_path = run_dir / "delay_sweep.csv"
    summaries = []
    all_afes_pass = True
    plot_errors: list[str] = []

    returned_afes = [int(afe_result.afe) for afe_result in response.afes]
    if len(returned_afes) != len(set(returned_afes)):
        raise RuntimeError("server response contains duplicate AFE results")
    if set(returned_afes) != set(requested_afes):
        raise RuntimeError(
            "server response AFE set does not match the request: "
            f"requested={requested_afes}, returned={returned_afes}"
        )

    with csv_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=(
                "afe",
                "channel",
                "tap",
                "failures",
                "transitions",
                "error_rate",
                "passing",
            ),
        )
        writer.writeheader()

        for afe_result in response.afes:
            afe = int(afe_result.afe)
            points = list(afe_result.points)
            if not points:
                raise RuntimeError(f"AFE{afe} response contains no sweep points")
            taps = [int(point.tap) for point in points]
            transitions = [int(point.transitionsPerChannel) for point in points]
            if any(len(point.channelFailures) != 8 for point in points):
                raise RuntimeError(
                    f"AFE{afe} response does not contain eight channel counts per tap"
                )
            failure_matrix = [
                [int(point.channelFailures[lane]) for point in points]
                for lane in range(8)
            ]
            eye = summarize_afe_eye(
                taps,
                failure_matrix,
                transitions,
                max_error_rate=args.max_error_rate,
            )

            print(
                f"AFE{afe}: original_delay={afe_result.originalDelay}, "
                f"bitslip={afe_result.bitslip}"
            )
            for lane, window in enumerate(eye.channel_windows):
                status = "PASS" if window is not None else "FAIL"
                print(
                    f"  [{status}] ch{afe * 8 + lane:02d}: "
                    f"passing eye {format_window(window)}"
                )
            if eye.common_window is None:
                all_afes_pass = False
                print("  [FAIL] no delay window is valid for all eight channels")
            else:
                print(
                    "  [PASS] common eye " + format_window(eye.common_window)
                )

            for lane, failures_by_tap in enumerate(failure_matrix):
                for tap, failures, total in zip(
                    taps, failures_by_tap, transitions
                ):
                    error_rate = failures / total
                    writer.writerow(
                        {
                            "afe": afe,
                            "channel": afe * 8 + lane,
                            "tap": tap,
                            "failures": failures,
                            "transitions": total,
                            "error_rate": f"{error_rate:.12g}",
                            "passing": int(error_rate <= args.max_error_rate),
                        }
                    )

            try:
                plot_heatmap(
                    run_dir,
                    afe,
                    taps,
                    failure_matrix,
                    eye.common_window,
                )
            except Exception as error:
                plot_errors.append(f"AFE{afe}: {error}")

            summaries.append(
                {
                    "afe": afe,
                    "original_delay": int(afe_result.originalDelay),
                    "bitslip": int(afe_result.bitslip),
                    "tested_taps": taps,
                    "channel_windows": [
                        None if window is None else asdict(window)
                        for window in eye.channel_windows
                    ],
                    "common_window": (
                        None
                        if eye.common_window is None
                        else asdict(eye.common_window)
                    ),
                }
            )

    summary = {
        "result": "PASS" if all_afes_pass else "FAIL",
        "server_success": bool(response.success),
        "server_message": response.message,
        "original_vtc_enable": int(response.originalVtcEnable),
        "endpoint": f"tcp://{args.ip}:{args.port}",
        "route": args.route,
        "requested_afes": requested_afes,
        "first_tap": args.first_tap,
        "last_tap": args.last_tap,
        "tap_step": args.tap_step,
        "samples": args.samples,
        "waveforms_per_tap": args.waveforms,
        "settle_time_us": args.settle_us,
        "maximum_passing_error_rate": args.max_error_rate,
        "afes": summaries,
        "plot_errors": plot_errors,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for error in plot_errors:
        print(f"[WARN] heatmap not generated: {error}")
    return run_dir, all_afes_pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep the common AFE IDELAY using synchronized ramp data and "
            "save per-channel error maps."
        )
    )
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--route", default="mezz/0")
    parser.add_argument("--afes", default="0,3,4")
    parser.add_argument("--first-tap", type=int, default=0)
    parser.add_argument("--last-tap", type=int, default=511)
    parser.add_argument("--tap-step", type=int, default=4)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--waveforms", type=int, default=8)
    parser.add_argument("--settle-us", type=int, default=10)
    parser.add_argument("--timeout-ms", type=int, default=600000)
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.0,
        help="Maximum ramp error fraction for a tap to pass (default: zero).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("afe_delay_sweep_results"),
    )
    args = parser.parse_args()

    try:
        afes = parse_indices(args.afes, maximum=4)
    except ValueError as error:
        parser.error(str(error))
    if args.first_tap < 0 or args.last_tap > 511:
        parser.error("tap range must be within 0..511")
    if args.first_tap > args.last_tap:
        parser.error("--first-tap cannot exceed --last-tap")
    if args.tap_step <= 0:
        parser.error("--tap-step must be greater than zero")
    if args.samples < 2 or args.samples > 2048:
        parser.error("--samples must be in 2..2048")
    if args.waveforms <= 0:
        parser.error("--waveforms must be greater than zero")
    if args.settle_us < 0 or args.settle_us > 1000000:
        parser.error("--settle-us must be in 0..1000000")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be greater than zero")
    if args.max_error_rate < 0.0 or args.max_error_rate > 1.0:
        parser.error("--max-error-rate must be in 0..1")

    try:
        pb = load_protobuf_module()
        print("DAPHNE AFE input-delay ramp sweep")
        print(f"  endpoint       : tcp://{args.ip}:{args.port}")
        print(f"  route          : {args.route}")
        print(f"  AFEs           : {afes}")
        print(
            f"  taps           : {args.first_tap}..{args.last_tap} "
            f"step {args.tap_step}"
        )
        print(f"  samples        : {args.samples}")
        print(f"  waveforms/tap  : {args.waveforms}")
        print("  trigger        : software (server-side)")
        print("[INFO] The server will restore AFE output, IDELAY and VTC state.")

        response = run_sweep(pb, args, afes)
        if not response.success:
            print(f"[FAIL] {response.message}")
            return 1
        run_dir, passed = save_results(response, args, afes)
        print(f"[INFO] detailed results: {run_dir}")
        if passed:
            print("[PASS] every requested AFE has a common eight-channel eye")
            return 0
        print("[FAIL] at least one requested AFE has no common eight-channel eye")
        return 1
    except KeyboardInterrupt:
        print(
            "[FAIL] interrupted by user; the server-side scan continues and "
            "restores the hardware before accepting another request"
        )
        return 130
    except Exception as error:
        print(f"[FAIL] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
