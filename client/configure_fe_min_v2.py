#!/usr/bin/env python3
"""
configure_fe_min_v2.py
Send CONFIGURE_FE via EnvelopeV2 and print full transport metadata
(task_id, msg_id, correl_id, timestamps, sizes) plus a response summary.

Usage:
  python3 configure_fe_min_v2.py 127.0.0.1 9876
  python3 configure_fe_min_v2.py 127.0.0.1 9876 --full
  python3 configure_fe_min_v2.py 127.0.0.1 9876 --json
"""

import os
import time
import zmq
import sys
import argparse
import random
import json
from datetime import datetime, timezone

# Import generated protos
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low
from client_dictionaries import (
    lpf_dict,
    pga_clamp_level_dict,
    pga_gain_control_dict,
    lna_gain_control_dict,
    lna_input_clamp_dict,
)


# ----------------- Helpers -----------------

def set_adc_fields(adc, *, resolution=True, output_format=True, sb_first=True):
    if hasattr(adc, "resolution"):
        adc.resolution = resolution
    if hasattr(adc, "output_format"):
        adc.output_format = output_format
    for name in ("sb_first", "SB_first"):
        if hasattr(adc, name):
            setattr(adc, name, sb_first)
            break


def make_default_config(
    ip="10.73.137.161",
    slot=0,
    timeout_ms=500,
    biasctrl=1300,
    self_trigger_threshold=0xc,  # 8000
    self_trigger_xcorr=0x68,
    tp_conf=0x0010DB35,
    compensator=0xFFFFFFFFFF,       # 48-bit in uint64
    inverters=0xFF00000000,         # 48-bit in uint64
    per_ch_trim=0,
    per_ch_offset=2275,
    vgain=1600,
    lpf_cutoff=4,
    pga_clamp_level=2,
    pga_gain=0,
    lna_gain=2,
    lna_clamp=0,
):
    cfg = pb_high.ConfigureRequest()
    cfg.daphne_address         = ip
    cfg.slot                   = slot
    cfg.timeout_ms             = timeout_ms
    cfg.biasctrl               = biasctrl
    cfg.self_trigger_threshold = self_trigger_threshold
    cfg.self_trigger_xcorr     = self_trigger_xcorr
    cfg.tp_conf                = tp_conf
    cfg.compensator            = compensator
    cfg.inverters              = inverters

    # Channels
    for ch in range(40):
        c = cfg.channels.add()
        c.id     = ch
        c.trim   = per_ch_trim
        c.offset = per_ch_offset
        c.gain   = 1

    # AFEs
    for afe in range(5):
        a = cfg.afes.add()
        a.id          = afe
        a.attenuators = vgain
        a.v_bias      = 0
        set_adc_fields(a.adc, resolution=True, output_format=True, sb_first=False)
        a.pga.lpf_cut_frequency  = lpf_cutoff
        a.pga.integrator_disable = True
        a.pga.gain               = pga_gain
        a.lna.clamp              = lna_clamp
        a.lna.gain               = lna_gain
        a.lna.integrator_disable = True

    return cfg


# Simple ID generator
_PID   = os.getpid()
_RAND  = random.randrange(1 << 30)
_SEQ   = 0
def next_ids():
    global _SEQ
    _SEQ += 1
    now_ns = time.time_ns()
    task_id = (now_ns << 16) ^ (_PID << 8) ^ (_RAND & 0xFF)
    msg_id  = (now_ns << 1) ^ _SEQ
    # keep positive 63-bit for readability
    return task_id & ((1 << 63) - 1), msg_id & ((1 << 63) - 1)


def build_configure_v2_envelope(cfg, *, route: str | None = None):
    env = pb_high.ControlEnvelopeV2()
    env.version   = 2
    env.dir       = pb_high.DIR_REQUEST
    env.type      = pb_high.MT2_CONFIGURE_FE_REQ
    env.payload   = cfg.SerializeToString()
    task_id, msg_id = next_ids()
    env.task_id   = task_id
    env.msg_id    = msg_id
    env.timestamp_ns = time.time_ns()
    if route:
        env.route = route
    return env


def enum_name(enum_cls, value):
    try:
        return enum_cls.Name(value)
    except Exception:
        return f"<unknown:{value}>"


def ns_to_iso(ns: int) -> str:
    # If it's tiny or zero, it's likely monotonic or unset
    if not ns or ns < 10**12:
        return f"(monotonic or unset) {ns} ns"
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat()


def short(u: int) -> str:
    return f"{u} (0x{u:016x})"


def print_envelope(label, env: pb_high.ControlEnvelopeV2, *, show_payload_len=True):
    dir_name  = enum_name(pb_high.Direction, env.dir)
    type_name = enum_name(pb_high.MessageTypeV2, env.type)
    print(f"[{label}]")
    print(f"  version      : {env.version}")
    print(f"  dir          : {dir_name} ({env.dir})")
    print(f"  type         : {type_name} ({env.type})")
    print(f"  task_id      : {short(env.task_id)}")
    print(f"  msg_id       : {short(env.msg_id)}")
    if env.correl_id:
        print(f"  correl_id    : {short(env.correl_id)}")
    if env.route:
        print(f"  route        : {env.route}")
    if env.timestamp_ns:
        print(f"  timestamp_ns : {env.timestamp_ns}  ->  {ns_to_iso(env.timestamp_ns)}")
    if show_payload_len:
        kib = len(env.payload) / 1024
        print(f"  payload_size : {len(env.payload)} bytes ({kib:.1f} KiB)")
    print()


def summarize_configure_response(resp: pb_high.ConfigureResponse, *, full=False):
    print("ConfigureResponse:")
    print(f"  success : {resp.success}")
    lines = resp.message.splitlines()
    if full or len(lines) <= 20:
        head = lines
        tail_note = ""
    else:
        head = lines[:20]
        tail_note = f"... (truncated, total {len(lines)} lines)"
    print("  message:")
    for ln in head:
        print("    " + ln)
    if tail_note:
        print("    " + tail_note)
    print()


# ----------------- Main -----------------

def main():
    ap = argparse.ArgumentParser(description="Send CONFIGURE_FE via EnvelopeV2 and print transport metadata.")
    ap.add_argument("-ip", "--ip", dest="host", default="127.0.0.1", help="Server IP")
    ap.add_argument("-port", "--port", dest="port", type=int, default=9876, help="Server port")
    ap.add_argument("--route", default="mezz/0", help="Optional logical route")
    ap.add_argument("--timeout", type=int, default=6000, help="Socket timeout (ms)")
    ap.add_argument("--full", action="store_true", help="Print full ConfigureResponse message")
    ap.add_argument("--json", action="store_true", help="Emit a JSON summary to stdout at the end")
    ap.add_argument("-vgain", type=int, default=1600, help="AFE attenuator code (default 1600)")
    ap.add_argument("-ch_offset", type=int, default=2275, help="Channel offset DAC code (default 2275)")
    ap.add_argument("-align_afes", action="store_true", help="Request AFE alignment (handled server-side after configure)")
    ap.add_argument("-lpf_cutoff", type=int, choices=lpf_dict.keys(), default=10, help="LPF cutoff MHz (10/15/20/30)")
    ap.add_argument("-pga_clamp_level", type=str, choices=pga_clamp_level_dict.keys(), default="0 dBFS")
    ap.add_argument("-pga_gain_control", type=str, choices=pga_gain_control_dict.keys(), default="24 dB")
    ap.add_argument("-lna_gain_control", type=str, choices=lna_gain_control_dict.keys(), default="12 dB")
    ap.add_argument("-lna_input_clamp", type=str, choices=lna_input_clamp_dict.keys(), default="auto")
    ap.add_argument("--adc_resolution", type=int, choices=[0, 1], default=1, help="ADC resolution bit (0/1)")
    args = ap.parse_args()

    endpoint = f"tcp://{args.host}:{args.port}"
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, b"client-v2-meta")
    sock.setsockopt(zmq.RCVTIMEO, args.timeout)
    sock.setsockopt(zmq.SNDTIMEO, args.timeout)
    sock.connect(endpoint)

    lpf_val = lpf_dict[args.lpf_cutoff]
    pga_clamp_val = pga_clamp_level_dict[args.pga_clamp_level]
    pga_gain_val = pga_gain_control_dict[args.pga_gain_control]
    lna_gain_val = lna_gain_control_dict[args.lna_gain_control]
    lna_clamp_val = lna_input_clamp_dict[args.lna_input_clamp]

    cfg = make_default_config(
        ip=args.host,
        per_ch_offset=args.ch_offset,
        vgain=args.vgain,
        lpf_cutoff=lpf_val,
        pga_clamp_level=pga_clamp_val,
        pga_gain=pga_gain_val,
        lna_gain=lna_gain_val,
        lna_clamp=lna_clamp_val,
    )
    for afe in cfg.afes:
        if hasattr(afe.adc, "resolution"):
            afe.adc.resolution = bool(args.adc_resolution)
    req = build_configure_v2_envelope(cfg, route=args.route)

    # Client timestamps & send
    t_send_ns = time.time_ns()
    print_envelope("REQUEST", req)
    sock.send(req.SerializeToString())

    # Receive multipart; last frame is payload
    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())
    reply_bytes = frames[-1]
    t_recv_ns = time.time_ns()
    rtt_ms = (t_recv_ns - t_send_ns) / 1e6

    # Parse response envelope
    reply = pb_high.ControlEnvelopeV2()
    if not reply.ParseFromString(reply_bytes):
        print("Failed to parse ControlEnvelopeV2 reply")
        return 2

    print_envelope("RESPONSE", reply)
    print(f"[METRICS]")
    print(f"  client_send_iso  : {ns_to_iso(t_send_ns)}")
    print(f"  client_recv_iso  : {ns_to_iso(t_recv_ns)}")
    print(f"  client_RTT_ms    : {rtt_ms:.2f}")
    if reply.timestamp_ns:
        print(f"  server_ts_iso    : {ns_to_iso(reply.timestamp_ns)}")
    print()

    # Correlation & type checks
    expected_type = pb_high.MT2_CONFIGURE_FE_RESP
    errors = []
    if reply.dir != pb_high.DIR_RESPONSE:
        errors.append(f"dir mismatch: got {reply.dir}")
    if reply.type != expected_type:
        errors.append(f"type mismatch: got {reply.type}, expected {expected_type}")
    if reply.task_id != req.task_id:
        errors.append(f"task_id mismatch: got {reply.task_id}, expected {req.task_id}")
    if reply.correl_id != req.msg_id:
        errors.append(f"correl_id mismatch: got {reply.correl_id}, expected {req.msg_id}")
    if errors:
        print("Correlation/Type checks FAILED:")
        for e in errors:
            print("  - " + e)
        print()

    # Decode typed payload
    out = pb_high.ConfigureResponse()
    if not out.ParseFromString(reply.payload):
        print("Failed to parse ConfigureResponse")
        return 6

    summarize_configure_response(out, full=args.full)

    align_json = None
    if args.align_afes:
        align_req = pb_low.cmd_alignAFEs()
        align_env = pb_high.ControlEnvelopeV2()
        align_env.version = 2
        align_env.dir = pb_high.DIR_REQUEST
        align_env.type = pb_high.MT2_ALIGN_AFE_REQ
        align_env.payload = align_req.SerializeToString()
        align_env.task_id, align_env.msg_id = next_ids()
        align_env.timestamp_ns = time.time_ns()
        align_env.route = args.route

        t_align_send = time.time_ns()
        print_envelope("ALIGN REQUEST", align_env)
        sock.send(align_env.SerializeToString())

        align_frames = [sock.recv()]
        while sock.getsockopt(zmq.RCVMORE):
            align_frames.append(sock.recv())
        align_reply_bytes = align_frames[-1]
        t_align_recv = time.time_ns()
        align_rtt_ms = (t_align_recv - t_align_send) / 1e6

        align_reply = pb_high.ControlEnvelopeV2()
        if not align_reply.ParseFromString(align_reply_bytes):
            print("Failed to parse ControlEnvelopeV2 align reply")
            return 7

        print_envelope("ALIGN RESPONSE", align_reply)
        print(f"[ALIGN_METRICS]")
        print(f"  client_send_iso  : {ns_to_iso(t_align_send)}")
        print(f"  client_recv_iso  : {ns_to_iso(t_align_recv)}")
        print(f"  client_RTT_ms    : {align_rtt_ms:.2f}")
        if align_reply.timestamp_ns:
            print(f"  server_ts_iso    : {ns_to_iso(align_reply.timestamp_ns)}")
        print()

        align_errors = []
        if align_reply.dir != pb_high.DIR_RESPONSE:
            align_errors.append(f"dir mismatch: got {align_reply.dir}")
        if align_reply.type != pb_high.MT2_ALIGN_AFE_RESP:
            align_errors.append(f"type mismatch: got {align_reply.type}, expected {pb_high.MT2_ALIGN_AFE_RESP}")
        if align_reply.task_id != align_env.task_id:
            align_errors.append(f"task_id mismatch: got {align_reply.task_id}, expected {align_env.task_id}")
        if align_reply.correl_id != align_env.msg_id:
            align_errors.append(f"correl_id mismatch: got {align_reply.correl_id}, expected {align_env.msg_id}")
        if align_errors:
            print("Align correlation/type checks FAILED:")
            for e in align_errors:
                print("  - " + e)
            print()

        align_out = pb_low.cmd_alignAFEs_response()
        if not align_out.ParseFromString(align_reply.payload):
            print("Failed to parse cmd_alignAFEs_response")
            return 8

        print("[ALIGN_RESULT]")
        print(f"  success : {align_out.success}")
        for ln in align_out.message.splitlines():
            print("  " + ln)
        print()

        align_json = {
            "request": {
                "version": align_env.version, "dir": int(align_env.dir), "type": int(align_env.type),
                "task_id": align_env.task_id, "msg_id": align_env.msg_id,
                "route": align_env.route, "timestamp_ns": align_env.timestamp_ns,
                "payload_size": len(align_env.payload),
            },
            "response": {
                "version": align_reply.version, "dir": int(align_reply.dir), "type": int(align_reply.type),
                "task_id": align_reply.task_id, "msg_id": align_reply.msg_id, "correl_id": align_reply.correl_id,
                "timestamp_ns": align_reply.timestamp_ns, "payload_size": len(align_reply.payload),
            },
            "metrics": {
                "client_send_ns": t_align_send, "client_recv_ns": t_align_recv, "rtt_ms": align_rtt_ms,
            },
            "align_response": {"success": align_out.success, "message_lines": align_out.message.count('\\n') + (1 if align_out.message else 0)},
        }

    if args.json:
        summary = {
            "endpoint": endpoint,
            "request": {
                "version": req.version, "dir": int(req.dir), "type": int(req.type),
                "task_id": req.task_id, "msg_id": req.msg_id,
                "route": req.route, "timestamp_ns": req.timestamp_ns,
                "payload_size": len(req.payload),
            },
            "response": {
                "version": reply.version, "dir": int(reply.dir), "type": int(reply.type),
                "task_id": reply.task_id, "msg_id": reply.msg_id, "correl_id": reply.correl_id,
                "timestamp_ns": reply.timestamp_ns, "payload_size": len(reply.payload),
            },
            "metrics": {
                "client_send_ns": t_send_ns, "client_recv_ns": t_recv_ns, "rtt_ms": rtt_ms,
            },
            "configure_response": {"success": out.success, "message_lines": out.message.count('\n') + (1 if out.message else 0)},
        }
        if align_json:
            summary["align"] = align_json
        print(json.dumps(summary, indent=2))

    return 0 if out.success else 1


if __name__ == "__main__":
    sys.exit(main())
