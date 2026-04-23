#!/usr/bin/env python3
"""
Exercise HD mezzanine EnvelopeV2 RPCs exposed by daphneServer.

Supported operations:
  - set-block-enable
  - configure-block
  - read-block-config
  - set-power-states
  - read-status
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from typing import Tuple

import zmq

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low


def next_ids() -> Tuple[int, int]:
    now_ns = time.time_ns()
    mask = (1 << 63) - 1
    return ((now_ns << 16) ^ random.randrange(1 << 16)) & mask, ((now_ns << 1) ^ random.randrange(1 << 16)) & mask


def v2_rpc(
    sock: zmq.Socket,
    req_type: int,
    req_msg,
    resp_type: int,
    resp_factory,
    *,
    route: str,
    timeout_ms: int,
):
    env = pb_high.ControlEnvelopeV2()
    env.version = 2
    env.dir = pb_high.DIR_REQUEST
    env.type = req_type
    env.payload = req_msg.SerializeToString()
    env.task_id, env.msg_id = next_ids()
    env.timestamp_ns = time.time_ns()
    if route:
        env.route = route

    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    sock.send(env.SerializeToString())

    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())

    rep = pb_high.ControlEnvelopeV2()
    if not rep.ParseFromString(frames[-1]):
        raise RuntimeError("Failed to parse ControlEnvelopeV2 reply")
    if rep.type != resp_type:
        raise RuntimeError(f"Unexpected response type {rep.type}, expected {resp_type}")
    if rep.correl_id and rep.correl_id != env.msg_id:
        raise RuntimeError(f"Correlation mismatch (got {rep.correl_id}, expected {env.msg_id})")

    resp = resp_factory()
    if not resp.ParseFromString(rep.payload):
        raise RuntimeError("Failed to parse response payload")
    return resp


def add_common_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--ip", default="127.0.0.1", help="Server IP")
    ap.add_argument("--port", type=int, default=9876, help="Server port")
    ap.add_argument("--route", default="mezz/0", help="EnvelopeV2 route")
    ap.add_argument("--identity", default="hdmezz-client", help="ZMQ identity")
    ap.add_argument("--timeout", type=int, default=5000, help="Per-request timeout (ms)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="HD mezzanine client for daphneServer (EnvelopeV2).")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("set-block-enable", help="Enable or disable one HD mezzanine block")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")
    p.add_argument("--enable", choices=["0", "1"], required=True, help="0=disable, 1=enable")

    p = sub.add_parser("configure-block", help="Configure one HD mezzanine block")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")
    p.add_argument("--rshunt-5v", type=float, required=True, help="5V shunt resistor value")
    p.add_argument("--rshunt-3v3", type=float, required=True, help="3V3 shunt resistor value")
    p.add_argument("--max-current-5v-scale", type=float, required=True, help="5V full-scale current")
    p.add_argument("--max-current-3v3-scale", type=float, required=True, help="3V3 full-scale current")
    p.add_argument("--max-current-5v-shutdown", type=float, required=True, help="5V shutdown current")
    p.add_argument("--max-current-3v3-shutdown", type=float, required=True, help="3V3 shutdown current")

    p = sub.add_parser("read-block-config", help="Read one HD mezzanine block configuration")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")

    p = sub.add_parser("set-power-states", help="Set 5V and 3V3 power states for one block")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")
    p.add_argument("--power-5v", choices=["0", "1"], required=True, help="0=off, 1=on")
    p.add_argument("--power-3v3", choices=["0", "1"], required=True, help="0=off, 1=on")

    p = sub.add_parser("read-status", help="Read cached HD mezzanine monitoring status")
    add_common_args(p)
    p.add_argument("--afe", type=int, required=True, choices=range(0, 5), help="AFE block [0..4]")

    return ap


def print_config_response(resp) -> None:
    print(f"success={resp.success} afe={resp.afeBlock} message='{resp.message}'")
    print(f"r_shunt_5V={resp.r_shunt_5V}")
    print(f"r_shunt_3V3={resp.r_shunt_3V3}")
    print(f"max_current_5V_scale={resp.max_current_5V_scale}")
    print(f"max_current_3V3_scale={resp.max_current_3V3_scale}")
    print(f"max_current_5V_shutdown={resp.max_current_5V_shutdown}")
    print(f"max_current_3V3_shutdown={resp.max_current_3V3_shutdown}")
    if hasattr(resp, "max_power_5V"):
        print(f"max_power_5V={resp.max_power_5V}")
        print(f"max_power_3V3={resp.max_power_3V3}")
        print(f"current_lsb_5V={resp.current_lsb_5V}")
        print(f"current_lsb_3V3={resp.current_lsb_3V3}")
        print(f"shunt_cal_5V={resp.shunt_cal_5V}")
        print(f"shunt_cal_3V3={resp.shunt_cal_3V3}")


def print_status_response(resp) -> None:
    print(f"success={resp.success} afe={resp.afeBlock} message='{resp.message}'")
    print(f"measured_voltage_5V={resp.measured_voltage5V}")
    print(f"measured_voltage_3V3={resp.measured_voltage3V3}")
    print(f"measured_current_5V={resp.measured_current5V}")
    print(f"measured_current_3V3={resp.measured_current3V3}")
    print(f"measured_power_5V={resp.measured_power5V}")
    print(f"measured_power_3V3={resp.measured_power3V3}")


def main() -> int:
    args = build_parser().parse_args()

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.DEALER)
    sock.setsockopt(zmq.IDENTITY, args.identity.encode())
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://{args.ip}:{args.port}")

    try:
        if args.command == "set-block-enable":
            req = pb_low.cmd_setHDMezzBlockEnable(id=0, afeBlock=args.afe, enable=bool(int(args.enable)))
            resp = v2_rpc(
                sock,
                pb_high.MT2_SET_HDMEZZ_BLOCK_ENABLE_REQ,
                req,
                pb_high.MT2_SET_HDMEZZ_BLOCK_ENABLE_RESP,
                pb_low.cmd_setHDMezzBlockEnable_response,
                route=args.route,
                timeout_ms=args.timeout,
            )
            print(f"success={resp.success} afe={resp.afeBlock} enable={int(resp.enable)} message='{resp.message}'")
            return 0 if resp.success else 2

        if args.command == "configure-block":
            req = pb_low.cmd_configureHDMezzBlock(
                id=0,
                afeBlock=args.afe,
                r_shunt_5V=args.rshunt_5v,
                r_shunt_3V3=args.rshunt_3v3,
                max_current_5V_scale=args.max_current_5v_scale,
                max_current_3V3_scale=args.max_current_3v3_scale,
                max_current_5V_shutdown=args.max_current_5v_shutdown,
                max_current_3V3_shutdown=args.max_current_3v3_shutdown,
            )
            resp = v2_rpc(
                sock,
                pb_high.MT2_CONFIGURE_HDMEZZ_BLOCK_REQ,
                req,
                pb_high.MT2_CONFIGURE_HDMEZZ_BLOCK_RESP,
                pb_low.cmd_configureHDMezzBlock_response,
                route=args.route,
                timeout_ms=args.timeout,
            )
            print_config_response(resp)
            return 0 if resp.success else 2

        if args.command == "read-block-config":
            req = pb_low.cmd_readHDMezzBlockConfig(id=0, afeBlock=args.afe)
            resp = v2_rpc(
                sock,
                pb_high.MT2_READ_HDMEZZ_BLOCK_CONFIG_REQ,
                req,
                pb_high.MT2_READ_HDMEZZ_BLOCK_CONFIG_RESP,
                pb_low.cmd_readHDMezzBlockConfig_response,
                route=args.route,
                timeout_ms=args.timeout,
            )
            print_config_response(resp)
            return 0 if resp.success else 2

        if args.command == "set-power-states":
            req = pb_low.cmd_setHDMezzPowerStates(
                id=0,
                afeBlock=args.afe,
                power5V=bool(int(args.power_5v)),
                power3V3=bool(int(args.power_3v3)),
            )
            resp = v2_rpc(
                sock,
                pb_high.MT2_SET_HDMEZZ_POWER_STATES_REQ,
                req,
                pb_high.MT2_SET_HDMEZZ_POWER_STATES_RESP,
                pb_low.cmd_setHDMezzPowerStates_response,
                route=args.route,
                timeout_ms=args.timeout,
            )
            print(
                f"success={resp.success} afe={resp.afeBlock} power5V={int(resp.power5V)} "
                f"power3V3={int(resp.power3V3)} message='{resp.message}'"
            )
            return 0 if resp.success else 2

        if args.command == "read-status":
            req = pb_low.cmd_readHDMezzStatus(id=0, afeBlock=args.afe)
            resp = v2_rpc(
                sock,
                pb_high.MT2_READ_HDMEZZ_STATUS_REQ,
                req,
                pb_high.MT2_READ_HDMEZZ_STATUS_RESP,
                pb_low.cmd_readHDMezzStatus_response,
                route=args.route,
                timeout_ms=args.timeout,
            )
            print_status_response(resp)
            return 0 if resp.success else 2

        raise RuntimeError(f"Unhandled command {args.command}")
    except zmq.Again:
        print("[timeout] no reply")
        return 2
    except Exception as exc:
        print(f"[error] {exc}")
        return 2
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
