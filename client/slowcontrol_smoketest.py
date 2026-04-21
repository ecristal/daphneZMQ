#!/usr/bin/env python3
"""
End-to-end smoketest client for daphneServer.

This exercises the main ControlEnvelopeV2 paths:
  - test register read (connectivity sanity)
  - general info fetch
  - trigger counters read
  - optional AFE align
  - optional configure (JSON input)
  - optional spybuffer chunk read

The script is non-destructive by default. Hardware-affecting steps
configure/align/spybuffer are opt-in via CLI flags.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from typing import Iterable, Optional, Tuple

import zmq

def _maybe_prefer_build_pb2() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    candidates = []
    env_build = os.environ.get("DAPHNE_BUILD_DIR")
    if env_build:
        candidates.append(env_build)
    candidates.extend(
        [
            os.path.join(repo_root, "build-test"),
            os.path.join(repo_root, "build-petalinux"),
            os.path.join(repo_root, "build"),
            os.path.join(repo_root, "build-local"),
            os.path.join(repo_root, "build-local2"),
        ]
    )

    for build_dir in candidates:
        pb2 = os.path.join(build_dir, "srcs", "protobuf", "daphneV3_high_level_confs_pb2.py")
        if os.path.isfile(pb2):
            if build_dir not in sys.path:
                sys.path.insert(0, build_dir)
            return


_maybe_prefer_build_pb2()

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low


# ----------------------------- Helpers -----------------------------

def make_dealer(endpoint: str, identity: Optional[bytes] = None) -> zmq.Socket:
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.DEALER)
    s.setsockopt(zmq.LINGER, 0)
    if identity is None:
        identity = f"smoketest-{uuid.uuid4()}".encode()
    s.setsockopt(zmq.IDENTITY, identity)
    s.connect(endpoint)
    return s


def next_ids() -> Tuple[int, int]:
    now_ns = time.time_ns()
    mask = (1 << 63) - 1  # keep within signed 63-bit
    return ((now_ns << 16) ^ random.randrange(1 << 16)) & mask, ((now_ns << 1) ^ random.randrange(1 << 16)) & mask


def send_v2(socket: zmq.Socket, mtype_req: int, payload_bytes: bytes, route: str, timeout_ms: int):
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = mtype_req
    env.payload = payload_bytes
    env.route = route
    env.task_id, env.msg_id = next_ids()
    env.timestamp_ns = time.time_ns()

    socket.send(env.SerializeToString())
    if not socket.poll(timeout_ms, zmq.POLLIN):
        raise TimeoutError(f"Timed out waiting for response to type={mtype_req}")

    frames = [socket.recv()]
    while socket.getsockopt(zmq.RCVMORE):
        frames.append(socket.recv())
    reply_bytes = frames[-1]

    rep = pb_high.ControlEnvelopeV2()
    rep.ParseFromString(reply_bytes)
    if rep.dir != pb_high.DIR_RESPONSE:
        raise RuntimeError(f"Unexpected dir={rep.dir} for type={mtype_req}")
    if rep.correl_id and rep.correl_id != env.msg_id:
        raise RuntimeError(f"Correlation mismatch (got {rep.correl_id}, expected {env.msg_id})")
    return rep


def load_config_request(json_path: str) -> pb_high.ConfigureRequest:
    with open(json_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    # Reuse the layout from np02-daphne-running.json
    first = next(iter(cfg.values()))
    req = pb_high.ConfigureRequest()
    req.daphne_address = first.get("daphne_address", "0.0.0.0")
    req.slot = first["slot"]
    req.timeout_ms = int(first.get("timeout_ms", 500))
    req.biasctrl = first["bias_ctrl"]
    req.self_trigger_threshold = int(first["self_trigger_threshold"])
    req.self_trigger_xcorr = int(first["self_trigger_xcorr"])
    req.tp_conf = int(first["tp_conf"])
    req.compensator = int(first["compensator"])
    req.inverters = int(first["inverter"])

    ch_conf = first["channel_analog_conf"]
    for cid, gain, offset, trim in zip(ch_conf["ids"], ch_conf["gains"], ch_conf["offsets"], ch_conf["trims"]):
        ch = req.channels.add()
        ch.id = cid
        ch.gain = gain
        ch.offset = offset
        ch.trim = trim

    afe_conf = first["afes"]
    for idx, att, vbias, adc, pga, lna in zip(
        afe_conf["ids"],
        afe_conf["attenuators"],
        afe_conf["v_biases"],
        afe_conf["adcs"],
        afe_conf["pgas"],
        afe_conf["lnas"],
    ):
        afe = req.afes.add()
        afe.id = idx
        afe.attenuators = att
        afe.v_bias = vbias

        afe_adc = afe.adc
        afe_adc.resolution = adc["resolution"]
        afe_adc.output_format = adc["output_format"]
        afe_adc.sb_first = adc.get("SB_first", adc.get("sb_first", False))

        afe_pga = afe.pga
        afe_pga.lpf_cut_frequency = pga["lpf_cut_frequency"]
        afe_pga.integrator_disable = pga["integrator_disable"]
        afe_pga.gain = pga["gain"]

        afe_lna = afe.lna
        afe_lna.clamp = lna["clamp"]
        afe_lna.integrator_disable = lna["integrator_disable"]
        afe_lna.gain = lna["gain"]

    if "full_stream_channels" in first:
        req.full_stream_channels.extend(first["full_stream_channels"])
    return req


def pretty_status(name: str, success: bool, message: str):
    status = "OK" if success else "FAIL"
    print(f"[{status}] {name}: {message}")


# ----------------------------- Actions -----------------------------

def do_test_reg(sock, route, timeout_ms):
    req = pb_high.TestRegRequest()
    rep = send_v2(sock, pb_high.MT2_READ_TEST_REG_REQ, req.SerializeToString(), route, timeout_ms)
    payload = pb_high.TestRegResponse()
    payload.ParseFromString(rep.payload)
    pretty_status("test_reg", True, f"value=0x{payload.value:08X} msg='{payload.message}'")


def do_general_info(sock, route, timeout_ms):
    req = pb_high.InfoRequest()
    rep = send_v2(sock, pb_high.MT2_READ_GENERAL_INFO_REQ, req.SerializeToString(), route, timeout_ms)
    # Server replies with GeneralInfo payload (not InfoResponse).
    gi = pb_high.GeneralInfo()
    if not gi.ParseFromString(rep.payload):
        # Fallback for older servers that used InfoResponse.
        legacy = pb_high.InfoResponse()
        legacy.ParseFromString(rep.payload)
        gi = legacy.general_info
    pretty_status(
        "general_info",
        True,
        f"vbias0={gi.v_bias_0:.3f} vbias1={gi.v_bias_1:.3f} temp={gi.temperature:.2f}C "
        f"p(-5V)={gi.power_minus5v:.3f} p(2p5V)={gi.power_plus2p5v:.3f}",
    )


def do_trigger_counters(sock, route, timeout_ms, channels: Iterable[int]):
    req = pb_high.ReadTriggerCountersRequest()
    req.channels.extend(channels)
    rep = send_v2(sock, pb_high.MT2_READ_TRIGGER_COUNTERS_REQ, req.SerializeToString(), route, timeout_ms)
    payload = pb_high.ReadTriggerCountersResponse()
    payload.ParseFromString(rep.payload)
    ok = payload.success
    msg = payload.message
    if payload.snapshots:
        sample = payload.snapshots[0]
        msg += f" first channel {sample.channel} trig={sample.record_count} busy={sample.busy_count}"
    pretty_status("trigger_counters", ok, msg)


def do_align(sock, route, timeout_ms):
    req = pb_low.cmd_alignAFEs()
    rep = send_v2(sock, pb_high.MT2_ALIGN_AFE_REQ, req.SerializeToString(), route, timeout_ms)
    payload = pb_low.cmd_alignAFEs_response()
    payload.ParseFromString(rep.payload)
    ok = payload.success
    delays = list(payload.delay)
    slips = list(payload.bitslip)
    pretty_status("align_afe", ok, f"delays={delays} bitslip={slips} msg='{payload.message}'")


def do_configure(sock, route, timeout_ms, json_path: str):
    req = load_config_request(json_path)
    rep = send_v2(sock, pb_high.MT2_CONFIGURE_FE_REQ, req.SerializeToString(), route, timeout_ms)
    payload = pb_high.ConfigureResponse()
    payload.ParseFromString(rep.payload)
    pretty_status("configure_fe", payload.success, payload.message)


def do_spybuffer(sock, route, timeout_ms, channels: Iterable[int], n_waveforms: int, n_samples: int):
    req = pb_high.DumpSpyBuffersChunkRequest()
    req.channelList.extend(int(ch) for ch in channels)
    req.numberOfSamples = n_samples
    req.numberOfWaveforms = n_waveforms
    req.softwareTrigger = False
    req.requestID = f"smoke-{uuid.uuid4()}"
    req.chunkSize = max(1, n_waveforms)

    rep = send_v2(sock, pb_high.MT2_DUMP_SPYBUFFER_CHUNK_REQ, req.SerializeToString(), route, timeout_ms)
    payload = pb_high.DumpSpyBuffersChunkResponse()
    payload.ParseFromString(rep.payload)
    ok = payload.success
    msg = payload.message
    pretty_status(
        "spybuffer_chunk",
        ok,
        f"{msg} waveforms={payload.waveformCount}/{payload.requestTotalWaveforms} "
        f"channels={list(payload.channelList)} samples={payload.numberOfSamples}",
    )


# ----------------------------- Main -----------------------------


def main():
    parser = argparse.ArgumentParser(description="Smoketest client for daphneServer (ControlEnvelopeV2).")
    parser.add_argument("-ip", default="127.0.0.1", help="Server IP (default 127.0.0.1)")
    parser.add_argument("-port", type=int, default=9876, help="Server port (default 9876)")
    parser.add_argument("--route", default="mezz/0", help="EnvelopeV2 route (default mezz/0)")
    parser.add_argument("--timeout_ms", type=int, default=5000, help="Per-request timeout in ms")

    parser.add_argument("--run-align", action="store_true", help="Invoke AFE alignment (hardware intrusive)")
    parser.add_argument("--run-configure", metavar="JSON", help="Send ConfigureRequest built from JSON file (hardware intrusive)")
    parser.add_argument("--run-spybuffer", action="store_true", help="Fetch one spybuffer chunk (hardware intrusive)")
    parser.add_argument("--spybuffer-channels", nargs="+", default=["0"], help="Channels for spybuffer chunk (default 0)")
    parser.add_argument("--spybuffer-waveforms", type=int, default=1, help="Waveforms per spybuffer chunk (default 1)")
    parser.add_argument("--spybuffer-samples", type=int, default=32, help="Samples per waveform (default 32)")
    parser.add_argument("--counter-channels", nargs="*", type=int, default=[], help="Trigger counter channels (empty=all)")

    args = parser.parse_args()

    endpoint = f"tcp://{args.ip}:{args.port}"
    sock = make_dealer(endpoint)

    # Always run the non-invasive checks
    do_test_reg(sock, args.route, args.timeout_ms)
    do_general_info(sock, args.route, args.timeout_ms)
    do_trigger_counters(sock, args.route, args.timeout_ms, args.counter_channels)

    if args.run_align:
        do_align(sock, args.route, max(args.timeout_ms, 20000))

    if args.run_configure:
        do_configure(sock, args.route, max(args.timeout_ms, 20000), args.run_configure)

    if args.run_spybuffer:
        do_spybuffer(
            sock,
            args.route,
            max(args.timeout_ms, 30000),
            args.spybuffer_channels,
            args.spybuffer_waveforms,
            args.spybuffer_samples,
        )

    sock.close()


if __name__ == "__main__":
    main()
