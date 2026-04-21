#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time

import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from configure_fe_min_v2 import make_default_config, next_ids


TRIG_BASE = 0xA0010000
TRIG_STRIDE = 0x20


def parse_channels(spec: str) -> list[int]:
    out: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a_str, b_str = token.split("-", 1)
            a = int(a_str, 0)
            b = int(b_str, 0)
            lo, hi = (a, b) if a <= b else (b, a)
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(token, 0))
    uniq: list[int] = []
    seen: set[int] = set()
    for ch in out:
        if ch < 0 or ch > 39:
            raise ValueError(f"channel out of range: {ch} (expected 0..39)")
        if ch not in seen:
            uniq.append(ch)
            seen.add(ch)
    if not uniq:
        raise ValueError("no channels selected")
    return uniq


def build_env(msg_type: int, payload: bytes, route: str) -> pb_high.ControlEnvelopeV2:
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = msg_type
    env.payload = payload
    env.task_id, env.msg_id = next_ids()
    env.timestamp_ns = time.time_ns()
    if route:
        env.route = route
    return env


def send_recv(sock: zmq.Socket, env: pb_high.ControlEnvelopeV2, expected_type: int) -> pb_high.ControlEnvelopeV2:
    sock.send(env.SerializeToString())
    reply = pb_high.ControlEnvelopeV2()
    if not reply.ParseFromString(sock.recv()):
        raise RuntimeError("failed to parse ControlEnvelopeV2 reply")
    if reply.type != expected_type:
        raise RuntimeError(f"unexpected reply type {reply.type}, expected {expected_type}")
    if reply.correl_id and reply.correl_id != env.msg_id:
        raise RuntimeError(f"unexpected correl_id {reply.correl_id}, expected {env.msg_id}")
    return reply


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Configure a threshold above 10 bits, then read trigger counters and print raw register checks."
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--route", default="mezz/0")
    ap.add_argument("--threshold", type=lambda s: int(s, 0), required=True, help="Threshold to send, e.g. 0x1200")
    ap.add_argument("--channels", default="0", help="Channel list/range, e.g. 0,3,5-7")
    ap.add_argument("--timeout", type=int, default=15000)
    ap.add_argument("--identity", default="client:thr14")
    args = ap.parse_args()

    channels = parse_channels(args.channels)
    endpoint = f"tcp://{args.host}:{args.port}"

    cfg = make_default_config(self_trigger_threshold=args.threshold, timeout_ms=min(args.timeout, 60000))
    del cfg.channels[:]
    for ch in channels:
        c = cfg.channels.add()
        c.id = ch
        c.trim = 0
        c.offset = 2275
        c.gain = 1

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, args.identity.encode("utf-8"))
    sock.setsockopt(zmq.RCVTIMEO, args.timeout)
    sock.setsockopt(zmq.SNDTIMEO, args.timeout)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(endpoint)

    try:
        req_env = build_env(pb_high.MT2_CONFIGURE_FE_REQ, cfg.SerializeToString(), args.route)
        rep_env = send_recv(sock, req_env, pb_high.MT2_CONFIGURE_FE_RESP)
        rep = pb_high.ConfigureResponse()
        if not rep.ParseFromString(rep_env.payload):
            raise RuntimeError("failed to parse ConfigureResponse")

        print(f"Endpoint  : {endpoint}")
        print(f"Route     : {args.route}")
        print(f"Channels  : {channels}")
        print(f"Requested : {args.threshold} (0x{args.threshold:X})")
        print(f"Configure : success={rep.success}")
        if rep.message:
            print("Message:")
            print(rep.message.rstrip())
        print()

        cnt_req = pb_high.ReadTriggerCountersRequest()
        cnt_req.channels.extend(channels)
        cnt_env = build_env(pb_high.MT2_READ_TRIGGER_COUNTERS_REQ, cnt_req.SerializeToString(), args.route)
        cnt_rep_env = send_recv(sock, cnt_env, pb_high.MT2_READ_TRIGGER_COUNTERS_RESP)
        cnt_rep = pb_high.ReadTriggerCountersResponse()
        if not cnt_rep.ParseFromString(cnt_rep_env.payload):
            raise RuntimeError("failed to parse ReadTriggerCountersResponse")

        print(f"Counters  : success={cnt_rep.success}")
        if cnt_rep.message:
            print(f"Message   : {cnt_rep.message.strip()}")
        print()
        print("Counter snapshot thresholds:")
        for snap in sorted(cnt_rep.snapshots, key=lambda s: s.channel):
            print(
                f"  ch={snap.channel:02d} "
                f"threshold_field={snap.threshold} "
                f"(0x{snap.threshold:X})"
            )
        print()
        print("Important: READ_TRIGGER_COUNTERS currently masks threshold readback to 10 bits on the server.")
        print("That means the snapshot above is not sufficient to prove full 14-bit storage for values > 0x3FF.")
        print()
        print("Raw register checks on the remote:")
        for ch in channels:
            addr = TRIG_BASE + ch * TRIG_STRIDE
            print(f"  ch={ch:02d} addr=0x{addr:08X}  devmem 0x{addr:08X} 32")
    finally:
        sock.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
