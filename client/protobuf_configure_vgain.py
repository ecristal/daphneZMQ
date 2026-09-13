#!/usr/bin/env python3
"""Configure one or all AFE VGAIN values through the V2 server API."""

import argparse
import sys

import zmq

from protobuf_loader import load_protobuf_modules
from v2_client import V2Client


def dac_code(value):
    parsed = int(value)
    if not 0 <= parsed <= 4095:
        raise argparse.ArgumentTypeError("expected an integer in 0..4095")
    return parsed


def build_parser():
    parser = argparse.ArgumentParser(description="Configure DAPHNE AFE VGAIN.")
    parser.add_argument("-ip", "--ip", default="127.0.0.1")
    parser.add_argument("-port", "--port", type=int, default=9876)
    parser.add_argument("-afe", "--afe", type=int, choices=range(5), default=0)
    parser.add_argument(
        "-vgain_value", "--vgain-value", type=dac_code, required=True
    )
    parser.add_argument(
        "-configure_all",
        "--configure-all",
        action="store_true",
        help="Configure all five AFEs with the same VGAIN value.",
    )
    parser.add_argument("-route", "--route", "-r", default="mezz/0")
    parser.add_argument(
        "--timeout-ms", "--timeout_ms", type=int, default=5000
    )
    parser.add_argument("--identity", default="configure-vgain-v2")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    failed = False
    try:
        pb_high, pb_low = load_protobuf_modules()
        with V2Client(
            pb_high,
            args.ip,
            args.port,
            route=args.route,
            timeout_ms=args.timeout_ms,
            identity=args.identity,
        ) as client:
            afe_blocks = range(5) if args.configure_all else (args.afe,)
            for afe in afe_blocks:
                request = pb_low.cmd_writeAFEVGAIN(
                    afeBlock=afe,
                    vgainValue=args.vgain_value,
                )
                response = client.rpc(
                    pb_high.MT2_WRITE_AFE_VGAIN_REQ,
                    request,
                    pb_high.MT2_WRITE_AFE_VGAIN_RESP,
                    pb_low.cmd_writeAFEVGAIN_response,
                )
                state = "PASS" if response.success else "FAIL"
                print(
                    f"[{state}] AFE {afe} VGAIN={response.vgainValue}: "
                    f"{response.message}"
                )
                failed = failed or not response.success
    except (RuntimeError, TimeoutError, zmq.ZMQError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
