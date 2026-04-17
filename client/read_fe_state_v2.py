#!/usr/bin/env python3
"""
Read front-end state via EnvelopeV2 without changing configuration.

Queries:
  - All channel trims
  - All channel offsets
  - AFE VGAIN (attenuators) per AFE
  - AFE bias set per AFE
  - Vbias control
  - Bias voltage monitor per AFE (cached values)
Optional:
  - Specific AFE register reads (--afe-reg AFE REG_ADDR)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Callable, Iterable, Tuple

import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from configure_fe_min_v2 import next_ids, ns_to_iso, print_envelope  # type: ignore
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low


def build_envelope(payload: bytes, msg_type: int, route: str | None = None) -> pb_high.ControlEnvelopeV2:
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = msg_type
    env.payload = payload
    env.task_id, env.msg_id = next_ids()
    env.timestamp_ns = time.time_ns()
    if route:
        env.route = route
    return env


def send_and_recv(
    sock: zmq.Socket,
    env: pb_high.ControlEnvelopeV2,
    expected_type: int,
    *,
    verbose: bool = True,
) -> pb_high.ControlEnvelopeV2:
    t_send = time.time_ns()
    if verbose:
        print_envelope("REQUEST", env, show_payload_len=False)
    sock.send(env.SerializeToString())

    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())
    reply_bytes = frames[-1]
    t_recv = time.time_ns()

    reply = pb_high.ControlEnvelopeV2()
    if not reply.ParseFromString(reply_bytes):
        raise RuntimeError("Failed to parse ControlEnvelopeV2 reply")

    if verbose:
        print_envelope("RESPONSE", reply, show_payload_len=False)
        print(f"[METRICS] send={ns_to_iso(t_send)} recv={ns_to_iso(t_recv)} rtt_ms={(t_recv - t_send)/1e6:.2f}\n")

    if reply.type != expected_type:
        raise RuntimeError(f"Unexpected response type {reply.type}, expected {expected_type}")
    if reply.correl_id and reply.correl_id != env.msg_id:
        raise RuntimeError(f"Correlation mismatch correl_id={reply.correl_id} expected={env.msg_id}")
    return reply


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Read FE state via EnvelopeV2 (no writes).")
    ap.add_argument("--host", default="127.0.0.1", help="Server IP")
    ap.add_argument("--port", type=int, default=9876, help="Server port")
    ap.add_argument("--route", default="mezz/0", help="Optional logical route")
    ap.add_argument("--timeout", type=int, default=6000, help="Socket timeout (ms)")
    ap.add_argument("--afe-count", type=int, default=5, help="Number of AFEs to query (default 5)")
    ap.add_argument("--skip-bias-monitor", action="store_true", help="Skip bias voltage monitor reads")
    ap.add_argument("--json", action="store_true", help="Emit the FE state snapshot as JSON only")
    ap.add_argument("--afe-reg", nargs=2, action="append", metavar=("AFE", "REG"), help="Read specific AFE register (board index, reg addr). Can be repeated.")
    return ap.parse_args()


def do_op(
    sock: zmq.Socket,
    req_msg,
    req_type: int,
    resp_type: int,
    resp_factory: Callable[[], object],
    label: str,
    *,
    verbose: bool = True,
):
    req_env = build_envelope(req_msg.SerializeToString(), req_type, route=args.route)
    reply_env = send_and_recv(sock, req_env, resp_type, verbose=verbose)
    resp = resp_factory()
    if not resp.ParseFromString(reply_env.payload):
        raise RuntimeError(f"Failed to parse response for {label}")
    if verbose:
        print(f"[{label}] success={getattr(resp, 'success', None)} message={getattr(resp, 'message', '').strip()}")
    return resp


def read_all(sock: zmq.Socket, args: argparse.Namespace, *, verbose: bool = True) -> dict:
    # Trims (all channels)
    trim_all = do_op(
        sock,
        pb_low.cmd_readTrim_allChannels(),
        pb_high.MT2_READ_TRIM_ALL_CH_REQ,
        pb_high.MT2_READ_TRIM_ALL_CH_RESP,
        pb_low.cmd_readTrim_allChannels_response,
        "READ_TRIM_ALL_CH",
        verbose=verbose,
    )

    # Offsets (all channels)
    offset_all = do_op(
        sock,
        pb_low.cmd_readOffset_allChannels(),
        pb_high.MT2_READ_OFFSET_ALL_CH_REQ,
        pb_high.MT2_READ_OFFSET_ALL_CH_RESP,
        pb_low.cmd_readOffset_allChannels_response,
        "READ_OFFSET_ALL_CH",
        verbose=verbose,
    )

    # Per-AFE data collectors
    afe_entries = []

    # VGAIN and Bias set per AFE
    for afe in range(args.afe_count):
        req_vg = pb_low.cmd_readAFEVgain(afeBlock=afe)
        resp_vg = do_op(
            sock,
            req_vg,
            pb_high.MT2_READ_AFE_VGAIN_REQ,
            pb_high.MT2_READ_AFE_VGAIN_RESP,
            pb_low.cmd_readAFEVgain_response,
            f"READ_AFE_VGAIN[afe={afe}]",
            verbose=verbose,
        )
        req_bias = pb_low.cmd_readAFEBiasSet(afeBlock=afe)
        resp_bias = do_op(
            sock,
            req_bias,
            pb_high.MT2_READ_AFE_BIAS_SET_REQ,
            pb_high.MT2_READ_AFE_BIAS_SET_RESP,
            pb_low.cmd_readAFEBiasSet_response,
            f"READ_AFE_BIAS_SET[afe={afe}]",
            verbose=verbose,
        )
        bias_monitor_val = None
        if not args.skip_bias_monitor:
            req_mon = pb_low.cmd_readBiasVoltageMonitor(afeBlock=afe)
            resp_mon = do_op(
                sock,
                req_mon,
                pb_high.MT2_READ_BIAS_VOLTAGE_MONITOR_REQ,
                pb_high.MT2_READ_BIAS_VOLTAGE_MONITOR_RESP,
                pb_low.cmd_readBiasVoltageMonitor_response,
                f"READ_BIAS_VOLTAGE_MONITOR[afe={afe}]",
                verbose=verbose,
            )
            if getattr(resp_mon, "success", False):
                bias_monitor_val = getattr(resp_mon, "biasVoltageValue", None)

        afe_entries.append(
            {
                "id": afe,
                "attenuators": getattr(resp_vg, "vgainValue", None),
                "v_bias": getattr(resp_bias, "biasValue", None),
                "bias_monitor_mV": bias_monitor_val,
            }
        )

    # Vbias control
    resp_vbias_ctrl = do_op(
        sock,
        pb_low.cmd_readVbiasControl(),
        pb_high.MT2_READ_VBIAS_CONTROL_REQ,
        pb_high.MT2_READ_VBIAS_CONTROL_RESP,
        pb_low.cmd_readVbiasControl_response,
        "READ_VBIAS_CONTROL",
        verbose=verbose,
    )

    # Optional AFE register reads
    if args.afe_reg:
        for afe_str, reg_str in args.afe_reg:
            afe = int(afe_str)
            reg_addr = int(reg_str, 0)
            req = pb_low.cmd_readAFEReg(afeBlock=afe, regAddress=reg_addr)
            do_op(
                sock,
                req,
                pb_high.MT2_READ_AFE_REG_REQ,
                pb_high.MT2_READ_AFE_REG_RESP,
                pb_low.cmd_readAFEReg_response,
                f"READ_AFE_REG[afe={afe},reg=0x{reg_addr:X}]",
                verbose=verbose,
            )

    # Pretty JSON-like output mirroring a seed structure
    offsets = list(getattr(offset_all, "offsetValues", []))
    trims = list(getattr(trim_all, "trimValues", []))
    bias_ctrl_val = getattr(resp_vbias_ctrl, "vBiasControlValue", None)

    config = {
        "channel_analog_conf": {
            "ids": list(range(40)),
            "gains": [1] * 40,
            "offsets": offsets,
            "trims": trims,
        },
        "afes": {
            "ids": [entry["id"] for entry in afe_entries],
            "attenuators": [entry["attenuators"] for entry in afe_entries],
            "v_biases": [entry["v_bias"] for entry in afe_entries],
            "bias_monitors_mV": [entry["bias_monitor_mV"] for entry in afe_entries],
        },
        "bias_ctrl": bias_ctrl_val,
    }
    if verbose:
        print("\n=== FE STATE SNAPSHOT (read-only) ===")
        print(json.dumps(config, indent=2))

    return config


if __name__ == "__main__":
    args = parse_args()

    endpoint = f"tcp://{args.host}:{args.port}"
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, b"client-v2-read")
    sock.setsockopt(zmq.RCVTIMEO, args.timeout)
    sock.setsockopt(zmq.SNDTIMEO, args.timeout)
    sock.connect(endpoint)

    if not args.json:
        print(f"Connected to {endpoint} route={args.route}")
    snapshot = read_all(sock, args, verbose=(not args.json))
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
