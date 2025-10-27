#!/usr/bin/env python3
import argparse, sys, time
from pathlib import Path
import zmq

# import protos when running from client/
PROTO_DIR = Path(__file__).resolve().parents[1] / "srcs" / "protobuf"
sys.path.append(str(PROTO_DIR))

def _try(name):
    try: return __import__(name, fromlist=["*"])
    except Exception: return None

mods = [m for m in (_try("daphneV3_low_level_confs_pb2"),
                    _try("daphneV3_high_level_confs_pb2")) if m]
P = next((m for m in mods if all(hasattr(m, x) for x in (
    "ControlEnvelopeV2","ReadTriggerCountersRequest","ReadTriggerCountersResponse",
    "MT2_READ_TRIGGER_COUNTERS_REQ","DIR_REQUEST"))), None)
if P is None:
    raise RuntimeError("No proto module with V2 envelope + counters messages found")

def now_ns(): return int(time.time_ns())
def make_msg_id(): return now_ns() & 0x7FFFFFFF
def parse_channels(spec):
    if not spec: return []
    out = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok: continue
        if "-" in tok:
            a,b = map(int, tok.split("-",1))
            lo,hi = (a,b) if a<=b else (b,a)
            out.extend(range(lo, hi+1))
        else:
            out.append(int(tok))
    seen, uniq = set(), []
    for c in out:
        if c not in seen: seen.add(c); uniq.append(c)
    return uniq
def fmt(n): return f"{n:,}".replace(",", "_")

def request(endpoint, route, channels, base_addr, timeout_ms):
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, timeout_ms)
    s.setsockopt(zmq.SNDTIMEO, timeout_ms)
    s.connect(endpoint)

    req = P.ReadTriggerCountersRequest()
    if channels: req.channels.extend(channels)
    if base_addr is not None: req.base_addr = int(base_addr)
    payload = req.SerializeToString()

    env = P.ControlEnvelopeV2()
    env.version = 2
    env.dir = P.DIR_REQUEST
    env.type = P.MT2_READ_TRIGGER_COUNTERS_REQ
    env.msg_id = make_msg_id()
    env.task_id = env.msg_id
    if hasattr(env, "timestamp_ns"): env.timestamp_ns = now_ns()
    if hasattr(env, "route") and route: env.route = route
    env.payload = payload

    s.send(env.SerializeToString())
    data = s.recv()  # raises Again on timeout

    resp_env = P.ControlEnvelopeV2()
    if not resp_env.ParseFromString(data) or not getattr(resp_env, "payload", b""):
        raise RuntimeError("Bad V2 response")
    resp = P.ReadTriggerCountersResponse()
    if not resp.ParseFromString(resp_env.payload):
        raise RuntimeError("Bad counters payload")
    return resp

def main():
    ap = argparse.ArgumentParser(description="Read trigger counters (V2)")
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--route", default="mezz/0")
    ap.add_argument("--channels", default="")
    ap.add_argument("--base", default=None)
    ap.add_argument("--timeout", type=int, default=6000)
    args = ap.parse_args()

    endpoint = f"tcp://{args.ip}:{args.port}"
    chans = parse_channels(args.channels)
    base = (int(args.base, 0) if isinstance(args.base, str) and args.base is not None
            else (int(args.base) if args.base is not None else None))

    try:
        resp = request(endpoint, args.route, chans, base, args.timeout)
    except Exception as e:
        print(f"[ERR] {e}")
        sys.exit(2)

    print(f"\nEndpoint: {endpoint}")
    print(f"Route   : {args.route}")
    if base is not None: print(f"Base    : 0x{base:08X}")
    print(f"Result  : {'SUCCESS' if resp.success else 'FAIL'}")
    if resp.message: print(f"Message : {resp.message}")
    if not resp.snapshots:
        print("No snapshots returned."); return
    cols = ("CH","THR(10b)","REC_CNT","BSY_CNT","FUL_CNT")
    widths = (4,9,16,16,16)
    def row(vals): return " ".join(f"{str(v):>{w}}" for v,w in zip(vals,widths))
    print("\n"+row(cols)); print(row("-"*w for w in widths))
    for s in sorted(resp.snapshots, key=lambda t: t.channel):
        print(row((s.channel, s.threshold & 0x3FF, fmt(s.record_count), fmt(s.busy_count), fmt(s.full_count))))

if __name__ == "__main__":
    main()