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
    "MT2_READ_TRIGGER_COUNTERS_REQ","MT2_READ_TRIGGER_COUNTERS_RESP","DIR_REQUEST"))), None)
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

def request(endpoint, route, channels, base_addr, timeout_ms, identity):
    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.DEALER)               # DEALER like the working testreg client
    s.setsockopt(zmq.IDENTITY, identity.encode("utf-8"))
    s.setsockopt(zmq.RCVTIMEO, timeout_ms)
    s.setsockopt(zmq.SNDTIMEO, timeout_ms)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(endpoint)

    req = P.ReadTriggerCountersRequest()
    if channels: req.channels.extend(channels)
    if base_addr is not None and hasattr(req, "base_addr"):
        req.base_addr = int(base_addr)

    env = P.ControlEnvelopeV2()
    env.version = 2
    env.dir = P.DIR_REQUEST
    env.type = P.MT2_READ_TRIGGER_COUNTERS_REQ
    env.msg_id = make_msg_id()
    env.task_id = env.msg_id
    if hasattr(env, "timestamp_ns"): env.timestamp_ns = now_ns()
    if hasattr(env, "route") and route: env.route = route
    env.payload = req.SerializeToString()

    s.send(env.SerializeToString())

    data = s.recv()  # raises Again on timeout
    resp_env = P.ControlEnvelopeV2()
    if not resp_env.ParseFromString(data) or not getattr(resp_env, "payload", b""):
        raise RuntimeError("Bad V2 response envelope")
    # Accept any type that carries counters payload
    resp = P.ReadTriggerCountersResponse()
    if not resp.ParseFromString(resp_env.payload):
        raise RuntimeError("Bad counters payload")
    return resp

def main():
    ap = argparse.ArgumentParser(description="Read trigger counters (V2, DEALER socket)")
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--route", default="mezz/0")
    ap.add_argument("--channels", default="")
    ap.add_argument("--base", default=None)
    ap.add_argument("--timeout", type=int, default=6000)
    ap.add_argument("--identity", default="client:cnt")   # fixed identity helps ROUTER routing
    args = ap.parse_args()

    endpoint = f"tcp://{args.ip}:{args.port}"
    chans = parse_channels(args.channels)
    base = (int(args.base, 0) if isinstance(args.base, str) and args.base is not None
            else (int(args.base) if args.base is not None else None))

    # Default: assume “real” response
    try:
        resp = request(endpoint, args.route, chans, base, args.timeout, args.identity)
        success = resp.success
        message = getattr(resp, "message", "")
    except Exception as e:
        # Friendly fallback so the table still prints
        success = False
        msg = str(e)
        if "Resource temporarily unavailable" in msg:
            msg = ("Timeout waiting for server reply "
                   "(check server running, port reachable, and that it speaks V2).")
        message = f"Client-side fallback: {msg}"
        # Fabricate zeros so the table shows structure
        resp = P.ReadTriggerCountersResponse()
        ch_list = chans if chans else list(range(40))
        for ch in ch_list:
            s = resp.snapshots.add()
            s.channel = ch
            s.threshold = 0
            s.record_count = 0
            s.busy_count = 0
            s.full_count = 0

    print(f"\nEndpoint: {endpoint}")
    print(f"Route   : {args.route}")
    if base is not None: print(f"Base    : 0x{base:08X}")
    print(f"Result  : {'SUCCESS' if success else 'FAIL'}")
    if message: print(f"Message : {message}")

    snaps = getattr(resp, "snapshots", [])
    if not snaps:
        print("No snapshots returned.")
        return

    cols = ("CH","THR(28b)","REC_CNT","BSY_CNT","FUL_CNT")
    widths = (4,9,16,16,16)
    def row(vals): return " ".join(f"{str(v):>{w}}" for v,w in zip(vals,widths))
    print("\n"+row(cols)); print(row("-"*w for w in widths))
    for s in sorted(snaps, key=lambda t: t.channel):
        print(row((s.channel, s.threshold,
                   f"{s.record_count:,}".replace(",","_"),
                   f"{s.busy_count:,}".replace(",","_"),
                   f"{s.full_count:,}".replace(",","_"))))

if __name__ == "__main__":
    main()
