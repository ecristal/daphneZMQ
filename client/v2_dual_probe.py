#!/usr/bin/env python3
import argparse, sys, time, binascii, textwrap
from pathlib import Path
import zmq

PROTO_DIR = Path(__file__).resolve().parents[1] / "srcs" / "protobuf"
sys.path.append(str(PROTO_DIR))

def _try(name):
    try: return __import__(name, fromlist=["*"])
    except Exception: return None

mods = [m for m in (_try("daphneV3_low_level_confs_pb2"),
                    _try("daphneV3_high_level_confs_pb2")) if m]
P = next((m for m in mods if all(hasattr(m, x) for x in (
    "ControlEnvelopeV2","TestRegRequest","TestRegResponse",
    "ReadTriggerCountersRequest","ReadTriggerCountersResponse",
    "MT2_READ_TEST_REG_REQ","MT2_READ_TEST_REG_RESP",
    "MT2_READ_TRIGGER_COUNTERS_REQ","MT2_READ_TRIGGER_COUNTERS_RESP",
    "DIR_REQUEST"))), None)
if P is None:
    raise RuntimeError("No V2 proto module found in srcs/protobuf with required symbols")

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
    print(f"  [V2] ver={getattr(env,'version',None)} dir={getattr(env,'dir',None)} "
          f"type={getattr(env,'type',None)} msg_id={getattr(env,'msg_id',None)} "
          f"task_id={getattr(env,'task_id',None)} correl_id={getattr(env,'correl_id',None)} "
          f"route='{getattr(env,'route','')}'")
    payload = getattr(env, "payload", b"")
    t = P.TestRegResponse()
    if payload and t.ParseFromString(payload):
        print(f"  [TestRegResp] value=0x{t.value:x} message='{t.message}'")
        return True
    c = P.ReadTriggerCountersResponse()
    if payload and c.ParseFromString(payload):
        print(f"  [CountersResp] success={c.success} message='{c.message}' snaps={len(c.snapshots)}")
        for s in c.snapshots[:10]:
            print(f"    ch={s.channel} thr={s.threshold} rec={s.record_count} bsy={s.busy_count} ful={s.full_count}")
        if len(c.snapshots) > 10:
            print(f"    … ({len(c.snapshots)-10} more)")
        return True
    if payload:
        print("  [V2] payload present but not TestReg/Counters")
    else:
        print("  [V2] empty payload")
    return True

def new_socket(ctx, endpoint, identity, timeout):
    s = ctx.socket(zmq.DEALER)             # DEALER like your working testreg_v2.py
    s.setsockopt(zmq.IDENTITY, identity.encode("utf-8"))
    s.setsockopt(zmq.SNDTIMEO, timeout)
    s.setsockopt(zmq.RCVTIMEO, timeout)
    s.setsockopt(zmq.LINGER, 0)
    s.connect(endpoint)
    return s

def send_and_recv(sock, frame: bytes, tag: str, timeout_ms: int):
    print(f"\n[send:{tag}] {len(frame)} bytes")
    hex_dump("out", frame)
    sock.send(frame)
    try:
        data = sock.recv()
        print(f"[recv:{tag}] {len(data)} bytes")
        hex_dump("in", data)
        parse_v2_and_print(data)
        return True, sock
    except zmq.Again:
        print(f"[recv:{tag}] timeout")
        return False, sock

def main():
    ap = argparse.ArgumentParser(description="Send V2 test-reg and counters, print raw and parsed replies.")
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument("--route", default="mezz/0")
    ap.add_argument("--identity", default="client:v2probe")
    ap.add_argument("--timeout", type=int, default=8000)
    ap.add_argument("--channels", default="")
    ap.add_argument("--base", default=None)
    args = ap.parse_args()

    endpoint = f"tcp://{args.ip}:{args.port}"
    print(f"[connect] {endpoint}  identity='{args.identity}'")

    ctx = zmq.Context.instance()
    s = new_socket(ctx, endpoint, args.identity, args.timeout)

    # 1) TEST-REG
    treq = P.TestRegRequest()
    env = P.ControlEnvelopeV2()
    env.version = 2; env.dir = P.DIR_REQUEST; env.type = P.MT2_READ_TEST_REG_REQ
    env.msg_id = make_msg_id(); env.task_id = env.msg_id
    if hasattr(env, "timestamp_ns"): env.timestamp_ns = now_ns()
    if hasattr(env, "route") and args.route: env.route = args.route
    env.payload = treq.SerializeToString()
    ok, s = send_and_recv(s, env.SerializeToString(), "test-reg", args.timeout)

    # If we timed out, RECREATE socket to avoid REQ/DEALER EFSM quirks
    if not ok:
        s.close(0)
        s = new_socket(ctx, endpoint, args.identity, args.timeout)

    # 2) COUNTERS
    creq = P.ReadTriggerCountersRequest()
    if args.base is not None and hasattr(creq, "base_addr"):
        creq.base_addr = int(args.base, 0) if isinstance(args.base, str) else int(args.base)
    if args.channels:
        for tok in args.channels.split(","):
            tok = tok.strip()
            if not tok: continue
            if "-" in tok:
                a,b = map(int, tok.split("-",1)); lo,hi = (a,b) if a<=b else (b,a)
                creq.channels.extend(range(lo, hi+1))
            else:
                creq.channels.append(int(tok))

    env2 = P.ControlEnvelopeV2()
    env2.version = 2; env2.dir = P.DIR_REQUEST; env2.type = P.MT2_READ_TRIGGER_COUNTERS_REQ
    env2.msg_id = make_msg_id(); env2.task_id = env2.msg_id
    if hasattr(env2, "timestamp_ns"): env2.timestamp_ns = now_ns()
    if hasattr(env2, "route") and args.route: env2.route = args.route
    env2.payload = creq.SerializeToString()
    send_and_recv(s, env2.SerializeToString(), "counters", args.timeout)

    print("\n[done]")

if __name__ == "__main__":
    main()
