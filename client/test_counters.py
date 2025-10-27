#!/usr/bin/env python3
# Read trigger counters via the V2 envelope, matching server expectations.

import argparse, sys, time
from pathlib import Path
import zmq

# Make generated protos importable when running from client/
PROTO_DIR = Path(__file__).resolve().parents[1] / "srcs" / "protobuf"
sys.path.append(str(PROTO_DIR))

def _try_import(name):
    try:
        return __import__(name, fromlist=["*"])
    except Exception:
        return None

# Load both, then pick the ONE module that has Envelope + Enum + DIR_REQUEST
mods = [m for m in (_try_import("daphneV3_low_level_confs_pb2"),
                    _try_import("daphneV3_high_level_confs_pb2")) if m]

def _select_proto_module():
    for m in mods:
        if all(hasattr(m, x) for x in ("ControlEnvelopeV2",
                                       "ReadTriggerCountersRequest",
                                       "ReadTriggerCountersResponse",
                                       "MT2_READ_TRIGGER_COUNTERS_REQ",
                                       "DIR_REQUEST")):
            return m
    raise RuntimeError("Could not find ONE proto module with V2 envelope + counters messages.")

P = _select_proto_module()

def now_ns() -> int:
    return int(time.time_ns())

def make_msg_id() -> int:
    return now_ns() & 0x7FFFFFFF

def parse_channels(spec: str):
    if not spec:
        return []
    out = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok: continue
        if "-" in tok:
            a, b = tok.split("-", 1)
            a, b = int(a), int(b)
            lo, hi = (a, b) if a <= b else (b, a)
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(tok))
    # dedupe preserving order
    seen, uniq = set(), []
    for c in out:
        if c not in seen:
            seen.add(c); uniq.append(c)
    return uniq

def fmt_int(n): return f"{n:,}".replace(",", "_")

def request_counters(endpoint: str, route: str, channels, base_addr: int | None, timeout_ms=6000):
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, timeout_ms)
    s.setsockopt(zmq.SNDTIMEO, timeout_ms)
    s.connect(endpoint)

    # Payload
    req = P.ReadTriggerCountersRequest()
    if channels:
        req.channels.extend(channels)
    if base_addr is not None:
        req.base_addr = int(base_addr)  # 0 means "use default" on server
    payload = req.SerializeToString()

    # V2 envelope — match your configure_fe_min_v2 shape
    env = P.ControlEnvelopeV2()
    env.version = 2
    env.dir = P.DIR_REQUEST
    env.type = P.MT2_READ_TRIGGER_COUNTERS_REQ
    env.msg_id = make_msg_id()
    env.task_id = env.msg_id
    if hasattr(env, "timestamp_ns"):
        env.timestamp_ns = now_ns()
    if hasattr(env, "route") and route:
        env.route = route
    env.payload = payload

    s.send(env.SerializeToString())
    data = s.recv()

    # Parse response (also V2 envelope)
    resp_env = P.ControlEnvelopeV2()
    if not resp_env.ParseFromString(data) or not getattr(resp_env, "payload", b""):
        raise RuntimeError("Bad response: not a ControlEnvelopeV2 or empty payload")

    resp = P.ReadTriggerCountersResponse()
    if not resp.ParseFromString(resp_env.payload):
        raise RuntimeError("Bad payload: cannot parse ReadTriggerCountersResponse")

    return resp

def main():
    ap = argparse.ArgumentParser(description="Read trigger counters via V2")
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--route", default="mezz/0", help="V2 route (match server), e.g. mezz/0")
    ap.add_argument("--channels", default="", help="e.g. 0-7,16,20,39")
    ap.add_argument("--base", default=None, help="Override base, e.g. 0xA0010000 (0 uses default)")
    ap.add_argument("--timeout", type=int, default=6000)
    args = ap.parse_args()

    endpoint = f"tcp://{args.ip}:{args.port}"
    channels = parse_channels(args.channels)
    base_addr = (int(args.base, 0) if isinstance(args.base, str) and args.base is not None
                 else (int(args.base) if args.base is not None else None))

    try:
        resp = request_counters(endpoint, args.route, channels, base_addr, timeout_ms=args.timeout)
    except Exception as e:
        print(f"[ERR] {e}")
        sys.exit(2)

    print(f"\nEndpoint: {endpoint}")
    print(f"Route   : {args.route}")
    if base_addr is not None:
        print(f"Base    : 0x{base_addr:08X}")
    print(f"Result  : {'SUCCESS' if resp.success else 'FAIL'}")
    if resp.message:
        print(f"Message : {resp.message}")

    if not resp.snapshots:
        print("No snapshots returned.")
        return

    # Table
    cols = ("CH", "THR(10b)", "REC_CNT", "BSY_CNT", "FUL_CNT")
    widths = (4, 9, 16, 16, 16)
    def row(vals): return " ".join(f"{str(v):>{w}}" for v, w in zip(vals, widths))

    print()
    print(row(cols))
    print(row("-"*w for w in widths))

    for s in sorted(resp.snapshots, key=lambda t: t.channel):
        print(row((s.channel, s.threshold & 0x3FF,
                   fmt_int(s.record_count),
                   fmt_int(s.busy_count),
                   fmt_int(s.full_count))))

if __name__ == "__main__":
    main()