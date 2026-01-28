#!/usr/bin/env python3
"""
Set a single AFE function via ControlEnvelopeV2.
Useful when the server is V2-only (ignores legacy ControlEnvelope).
"""
import argparse
import os
import sys
import time

import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low
from client_dictionaries import available_afe_functions


def next_ids():
    now_ns = time.time_ns()
    mask = (1 << 63) - 1
    return ((now_ns << 16) ^ 0xBEEF) & mask, ((now_ns << 1) ^ 0x1234) & mask


def validate_value(func: str, value: int) -> None:
    valid_range = available_afe_functions[func]
    if len(valid_range) == 2:
        lo, hi = valid_range
        if lo == 0 and hi == 1:
            if value not in (0, 1):
                raise ValueError(f"Invalid value for {func}: {value}. Expected 0 or 1.")
        else:
            if value < lo or value > hi:
                raise ValueError(f"Invalid value for {func}: {value}. Expected {lo}-{hi}.")
    else:
        if value not in valid_range:
            raise ValueError(f"Invalid value for {func}: {value}. Expected one of {valid_range}.")


def send_v2(sock: zmq.Socket, route: str, req_msg) -> pb_high.ControlEnvelopeV2:
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = pb_high.MT2_WRITE_AFE_FUNCTION_REQ
    env.payload = req_msg.SerializeToString()
    env.task_id, env.msg_id = next_ids()
    env.timestamp_ns = time.time_ns()
    if route:
        env.route = route

    sock.send(env.SerializeToString())
    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())
    rep = pb_high.ControlEnvelopeV2()
    rep.ParseFromString(frames[-1])
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="Set AFE function via EnvelopeV2.")
    ap.add_argument("-ip", default="127.0.0.1", help="Server IP")
    ap.add_argument("-port", type=int, default=9876, help="Server port")
    ap.add_argument("--route", default="mezz/0", help="Route for EnvelopeV2")
    ap.add_argument("--timeout", type=int, default=3000, help="ZMQ send/recv timeout (ms)")
    ap.add_argument("-afeFunction", required=True, choices=list(available_afe_functions.keys()))
    ap.add_argument("-afeNumber", type=int, choices=range(0, 5), help="AFE index 0..4")
    ap.add_argument("--all", action="store_true", help="Apply to all AFEs 0..4")
    ap.add_argument("-value", type=int, required=True, help="Function value to set")
    args = ap.parse_args()

    validate_value(args.afeFunction, args.value)
    if not args.all and args.afeNumber is None:
        ap.error("Provide -afeNumber or use --all")

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, b"afe-func-v2")
    sock.setsockopt(zmq.RCVTIMEO, args.timeout)
    sock.setsockopt(zmq.SNDTIMEO, args.timeout)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://{args.ip}:{args.port}")

    targets = range(5) if args.all else [args.afeNumber]
    for afe in targets:
        req = pb_low.cmd_writeAFEFunction()
        req.afeBlock = int(afe)
        req.function = args.afeFunction
        req.configValue = int(args.value)
        rep = send_v2(sock, args.route, req)
        if rep.type != pb_high.MT2_WRITE_AFE_FUNCTION_RESP:
            print(f"[error] unexpected reply type {rep.type} for AFE{afe}")
            continue
        out = pb_low.cmd_writeAFEFunction_response()
        out.ParseFromString(rep.payload)
        status = "OK" if out.success else "FAIL"
        print(f"[{status}] AFE{afe} {out.function}={out.configValue} :: {out.message}")

    sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
