#!/usr/bin/env python3
import argparse
import os
import sys
import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low


def main():
    ap = argparse.ArgumentParser(description="Read bias monitor once (V2).")
    ap.add_argument("--ip", default="127.0.0.1", help="Server IP (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=9876, help="Server port (default 9876)")
    ap.add_argument("--afe", type=int, default=0, choices=range(0, 5), help="AFE block to read [0..4]")
    ap.add_argument("--timeout", type=int, default=2000, help="ZMQ send/recv timeout (ms)")
    ap.add_argument("--route", default="mezz/0", help="Logical route")
    ap.add_argument("--identity", default="vbias-monitor", help="Dealer identity")
    args = ap.parse_args()

    endpoint = f"tcp://{args.ip}:{args.port}"
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.DEALER)
    s.setsockopt(zmq.IDENTITY, args.identity.encode())
    s.setsockopt(zmq.RCVTIMEO, args.timeout)
    s.setsockopt(zmq.SNDTIMEO, args.timeout)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(endpoint)

    req = pb_low.cmd_readBiasVoltageMonitor()
    req.id = 0
    req.afeBlock = args.afe

    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = pb_high.MT2_READ_BIAS_VOLTAGE_MONITOR_REQ
    env.payload = req.SerializeToString()
    env.route = args.route

    try:
        s.send(env.SerializeToString())
        frames = [s.recv()]
        while s.getsockopt(zmq.RCVMORE):
            frames.append(s.recv())
    except zmq.Again:
        print("[timeout] no reply")
        return 2

    rep = pb_high.ControlEnvelopeV2()
    rep.ParseFromString(frames[-1])

    if rep.type != pb_high.MT2_READ_BIAS_VOLTAGE_MONITOR_RESP:
        print(f"[error] unexpected reply type {rep.type}")
        return 2

    out = pb_low.cmd_readBiasVoltageMonitor_response()
    out.ParseFromString(rep.payload)

    if not out.success:
        print(f"[server error] {out.message}")
        return 2

    mv = out.biasVoltageValue
    print(f"AFE {out.afeBlock} bias = {mv / 1000.0:.3f} V ({mv} mV)   message='{out.message}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
