#!/usr/bin/env python3
"""Configure one AFE5808A function through the V2 server API."""

import argparse
import sys

import zmq

from client_dictionaries import available_afe_functions
from protobuf_loader import load_protobuf_modules
from v2_client import V2Client


def validate_function_value(function, value):
    valid_values = available_afe_functions[function]
    if len(valid_values) == 2:
        minimum, maximum = valid_values
        if not minimum <= value <= maximum:
            raise ValueError(
                f"invalid value for {function}: {value}; "
                f"expected {minimum}..{maximum}"
            )
    elif value not in valid_values:
        raise ValueError(
            f"invalid value for {function}: {value}; "
            f"expected one of {valid_values}"
        )


def build_parser():
    parser = argparse.ArgumentParser(description="Configure an AFE function.")
    parser.add_argument("-ip", "--ip", default="127.0.0.1")
    parser.add_argument("-port", "--port", type=int, default=9876)
    parser.add_argument(
        "-afeFunction",
        "--afe-function",
        dest="afe_function",
        required=True,
        choices=sorted(available_afe_functions),
    )
    parser.add_argument(
        "-afeNumber",
        "--afe-number",
        dest="afe_number",
        type=int,
        required=True,
        choices=range(5),
    )
    parser.add_argument("-value", "--value", type=int, required=True)
    parser.add_argument("-route", "--route", "-r", default="mezz/0")
    parser.add_argument(
        "--timeout-ms", "--timeout_ms", type=int, default=5000
    )
    parser.add_argument("--identity", default="configure-afe-function-v2")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_function_value(args.afe_function, args.value)
    except ValueError as exc:
        parser.error(str(exc))

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
            response = client.rpc(
                pb_high.MT2_WRITE_AFE_FUNCTION_REQ,
                pb_low.cmd_writeAFEFunction(
                    afeBlock=args.afe_number,
                    function=args.afe_function,
                    configValue=args.value,
                ),
                pb_high.MT2_WRITE_AFE_FUNCTION_RESP,
                pb_low.cmd_writeAFEFunction_response,
            )
            state = "PASS" if response.success else "FAIL"
            print(
                f"[{state}] AFE {args.afe_number} {args.afe_function}="
                f"{response.configValue}: {response.message}"
            )
            return 0 if response.success else 1
    except (RuntimeError, TimeoutError, zmq.ZMQError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
