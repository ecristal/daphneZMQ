#!/usr/bin/env python3
import argparse, sys, time, binascii, textwrap
from pathlib import Path
import zmq

# ---- import protos from srcs/protobuf ----
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
    raise RuntimeError("No proto module with V2 envelope + counters messages found in srcs/protobuf")

def now_ns(): return int(time.time_ns())
def make_msg_id(): return now_ns() & 0x7FFFFFFF

def hex_dump(label: str, data: bytes, width: int = 32):
    print(f"{label}: {len(data)} bytes")
    hx = binascii.hexlify(data).decode("ascii")
    for i in range(0, len(hx), width*2):
        chunk = hx[i:i+width*2]
        print("  " + " ".join(textwrap.wrap(chunk, 2)))

def parse_v2_and_print(b: bytes):
    env = P.ControlEnvelopeV2()
    if not env.ParseFromString(b):
        print("  [parse] Not a V2 ControlEnvelope")
        return False
    print(f"  [V2] version={getattr(env,'version',None)} dir={getattr(env,'dir',None)} "
          f"type={getattr(env,'type',None)} msg_id={getattr(env,'msg_id',None)} "
          f"task_id={getattr(env,'task_id',None)} correl_id={getattr(env,'correl_id',None)} "
          f"route='{getattr(env,'route','')}'")
    # Try counters payload
    try:
        payload = getattr(env, "payload", b"")
        if not payload:
            print("  [V2] empty payload")
            return True
        cnt = P.ReadTriggerCountersResponse()
        if cnt.ParseFromString(payload):
            print(f"  [V2][CountersResp] success={cnt.success} message='{cnt.message}' "
                  f"snapshots={len(cnt.snapshots)}")
            for s in cnt.snapshots[:10]:  # keep it readable
                print(f"    ch={s.channel} thr={s.threshold&0x3FF} rec={s.record_count} "
                      f"bsy={s.busy_count} ful={s.full_count}")
            if len(cnt.snapshots) > 10:
                print(f"    … ({len(cnt.snapshots)-10} more)")
            return True
        else:
            print("  [V2] payload is not ReadTriggerCountersResponse (might be another message)")
            return True
    except Exception as e:
        print(f"  [V2] payload parse error: {e}")
        return True

def main():
    ap = argparse.ArgumentParser(
        description="Send MT2_READ_TRIGGER_COUNTERS_REQ and listen verbosely to any replies.")
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--route", default="mezz/0")
    ap.add_argument("--channels", default="", help="e.g. '0-7,16,20'")
    ap.add_argument("--base", default=None, help="base addr (e.g. 0xA0010000)")
    ap.add_argument("--timeout", type=int, default=6000, help="per-recv timeout ms")
    ap.add_argument("--listen_ms", type=int, default=3000,
                    help="after first recv, keep listening this many ms for extra frames")
    ap.add_argument("--identity", default="client:cntsniff", help="ZMQ identity tag")
    args = ap.parse_args()

    # Build channel list
    chans = []
    if args.channels:
        for tok in args.channels.split(","):
            tok = tok.strip()
            if not tok: continue
            if "-" in tok:
                a,b = map(int, tok.split("-",1))
                lo,hi = (a,b) if a<=b else (b,a)
                chans.extend(range(lo, hi+1))
            else:
                chans.append(int(tok))
        # uniq preserve order
        seen, uniq = set(), []
        for c in chans:
            if c not in seen: seen.add(c); uniq.append(c)
        chans = uniq

    endpoint = f"tcp://{args.ip}:{args.port}"
    print(f"\n[connect] {endpoint}  identity='{args.identity}'")

    ctx = zmq.Context.instance()
    s = ctx.socket(zmq.REQ)
    s.setsockopt(zmq.RCVTIMEO, args.timeout)
    s.setsockopt(zmq.SNDTIMEO, args.timeout)
    s.setsockopt(zmq.IDENTITY, args.identity.encode("utf-8"))
    s.connect(endpoint)

    # Build request
    req = P.ReadTriggerCountersRequest()
    if chans: req.channels.extend(chans)
    if args.base is not None:
        base = int(args.base, 0) if isinstance(args.base, str) else int(args.base)
        # Only set if the field exists in this proto build
        if hasattr(req, "base_addr"):
            req.base_addr = base
    payload = req.SerializeToString()

    env = P.ControlEnvelopeV2()
    env.version = 2
    env.dir = P.DIR_REQUEST
    env.type = P.MT2_READ_TRIGGER_COUNTERS_REQ
    env.msg_id = make_msg_id()
    env.task_id = env.msg_id
    if hasattr(env, "timestamp_ns"): env.timestamp_ns = now_ns()
    if hasattr(env, "route") and args.route: env.route = args.route
    env.payload = payload

    out = env.SerializeToString()
    print(f"[send] MT2_READ_TRIGGER_COUNTERS_REQ  bytes={len(out)}")
    hex_dump("frame[0]", out)
    s.send(out)

    # Receive loop: print ANY reply; keep listening a bit after first reply
    poller = zmq.Poller()
    poller.register(s, zmq.POLLIN)

    got_any = False
    t_end_extra = None
    while True:
        remaining = args.timeout if not got_any else max(0, int(t_end_extra - time.time()*1000))
        if got_any and remaining == 0:
            break
        socks = dict(poller.poll(remaining))
        if s not in socks or socks[s] != zmq.POLLIN:
            if not got_any:
                print("[recv] timeout (no frames)")
            break
        data = s.recv()
        ts = time.strftime("%H:%M:%S")
        print(f"\n[{ts}] [recv] {len(data)} bytes")
        hex_dump("reply", data)
        parsed = parse_v2_and_print(data)
        if not parsed:
            print("  [note] Not a V2 envelope; could be legacy format or unexpected data.")
        if not got_any:
            got_any = True
            t_end_extra = time.time()*1000 + args.listen_ms

    print("\n[done]")

if __name__ == "__main__":
    main()

