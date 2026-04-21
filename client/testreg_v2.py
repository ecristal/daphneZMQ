#!/usr/bin/env python3
import os, sys, argparse, zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high

def main():
    ap = argparse.ArgumentParser(description="Read test register over V2 (returns 0xDEADBEEF)")
    ap.add_argument("ip", nargs="?", default="127.0.0.1")
    ap.add_argument("port", nargs="?", type=int, default=9876)
    ap.add_argument("--timeout", type=int, default=3000)
    ap.add_argument("--route", default="mezz/0")
    args = ap.parse_args()

    endpoint = f"tcp://{args.ip}:{args.port}"
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.DEALER)
    s.setsockopt(zmq.IDENTITY, b"testreg-v2")
    s.setsockopt(zmq.RCVTIMEO, args.timeout)
    s.setsockopt(zmq.SNDTIMEO, args.timeout)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(endpoint)

    # Empty request payload
    req = pb_high.TestRegRequest()

    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir     = pb_high.DIR_REQUEST
    env.type    = pb_high.MT2_READ_TEST_REG_REQ
    env.payload = req.SerializeToString()
    env.route   = args.route

    s.send(env.SerializeToString())
    frames = [s.recv()]
    while s.getsockopt(zmq.RCVMORE):
        frames.append(s.recv())
    rep = pb_high.ControlEnvelopeV2()
    rep.ParseFromString(frames[-1])

    if rep.type != pb_high.MT2_READ_TEST_REG_RESP:
        print(f"[FAIL] unexpected type {rep.type}")
        return 2

    out = pb_high.TestRegResponse()
    out.ParseFromString(rep.payload)
    print(f"[OK] test-reg value = 0x{out.value:08x}  ({out.message})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
