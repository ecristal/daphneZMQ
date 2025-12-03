#!/usr/bin/env python3
"""
Small client to exercise MT2_READ_GENERAL_INFO_REQ/RESP.

Note: regenerate protobufs after adding the enum to daphne_control_high.proto so
pb_high.MT2_READ_GENERAL_INFO_* exists:
  protoc --python_out=srcs/protobuf daphnemodules/schema/daphnemodules/daphne_control_high.proto
"""
import argparse
import os
import sys
import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high  # noqa


def main():
    ap = argparse.ArgumentParser(description="Read GeneralInfo via Envelope V2.")
    ap.add_argument("--ip", default="127.0.0.1", help="Server IP (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=9876, help="Server port (default 9876)")
    ap.add_argument("--route", default="mezz/0", help="Logical route (default mezz/0)")
    ap.add_argument("--identity", default="general-info", help="Dealer identity")
    ap.add_argument("--timeout", type=int, default=2000, help="ZMQ send/recv timeout (ms)")
    ap.add_argument("--level", type=int, default=0, help="InfoRequest.level (optional)")
    args = ap.parse_args()

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, args.identity.encode())
    sock.setsockopt(zmq.RCVTIMEO, args.timeout)
    sock.setsockopt(zmq.SNDTIMEO, args.timeout)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://{args.ip}:{args.port}")

    # Build InfoRequest
    req = pb_high.InfoRequest()
    req.level = args.level

    # Wrap in ControlEnvelopeV2
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = pb_high.MT2_READ_GENERAL_INFO_REQ
    env.payload = req.SerializeToString()
    env.route = args.route
    env.msg_id = 1
    env.task_id = 1

    sock.send(env.SerializeToString())
    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())

    rep = pb_high.ControlEnvelopeV2()
    rep.ParseFromString(frames[-1])
    if rep.type != pb_high.MT2_READ_GENERAL_INFO_RESP:
        raise RuntimeError(f"Unexpected reply type {rep.type}")

    out = pb_high.InfoResponse()
    out.ParseFromString(rep.payload)
    g = out.general_info

    print("GeneralInfo:")
    print(f"  v_bias_0:     {g.v_bias_0:.5f} V")
    print(f"  v_bias_1:     {g.v_bias_1:.5f} V")
    print(f"  v_bias_2:     {g.v_bias_2:.5f} V")
    print(f"  v_bias_3:     {g.v_bias_3:.5f} V")
    print(f"  v_bias_4:     {g.v_bias_4:.5f} V")
    print(f"  power_minus5v:{g.power_minus5v:.5f} V (rail)")
    print(f"  power_plus2p5v:{g.power_plus2p5v:.5f} V (rail)")
    print(f"  power_ce:     {g.power_ce:.5f} V (rail)")
    if g.HasField("temperature"):
        print(f"  temperature:  {g.temperature:.5f} C")


if __name__ == "__main__":
    main()
