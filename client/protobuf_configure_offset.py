#!/usr/bin/env python3
"""Configure one or all channel offsets through the V2 server API."""

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
    parser = argparse.ArgumentParser(description="Configure DAPHNE channel offset.")
    parser.add_argument("-ip", "--ip", default="127.0.0.1")
    parser.add_argument("-port", "--port", type=int, default=9876)
    parser.add_argument(
        "-channel", "--channel", type=int, choices=range(40), default=0
    )
    parser.add_argument(
        "-offset_value", "--offset-value", type=dac_code, required=True
    )
    parser.add_argument(
        "-configure_all",
        "--configure-all",
        action="store_true",
        help="Configure all 40 channels with the same offset.",
    )
    parser.add_argument("-route", "--route", "-r", default="mezz/0")
    parser.add_argument(
        "--timeout-ms", "--timeout_ms", type=int, default=5000
    )
    parser.add_argument("--identity", default="configure-offset-v2")
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
            channels = range(40) if args.configure_all else (args.channel,)
            for channel in channels:
                request = pb_low.cmd_writeOFFSET_singleChannel(
                    offsetChannel=channel,
                    offsetValue=args.offset_value,
                    offsetGain=False,
                )
                response = client.rpc(
                    pb_high.MT2_WRITE_OFFSET_CH_REQ,
                    request,
                    pb_high.MT2_WRITE_OFFSET_CH_RESP,
                    pb_low.cmd_writeOFFSET_singleChannel_response,
                )
                state = "PASS" if response.success else "FAIL"
                print(
                    f"[{state}] channel {channel} offset="
                    f"{response.offsetValue}: {response.message}"
                )
                failed = failed or not response.success
    except (RuntimeError, TimeoutError, zmq.ZMQError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
