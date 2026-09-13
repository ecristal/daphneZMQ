#!/usr/bin/env python3
"""Configure VBIAS control, one AFE bias, and one channel trim over V2."""

import argparse
import sys

import zmq

from protobuf_loader import load_protobuf_modules
from v2_client import V2Client


def bias_volts_to_dac(volts):
    return int((26.1 / (26.1 + 1000.0)) * 1000.0 * volts)


def bias_control_volts_to_dac(volts):
    return int((1.0 / 74.0) * volts * 1000.0)


def checked_dac_code(value, name):
    if not 0 <= value <= 4095:
        raise ValueError(f"{name} DAC code {value} is outside 0..4095")
    return value


def direct_dac_code(value, name):
    if not float(value).is_integer():
        raise ValueError(f"{name} must be an integer when -set_as_DAC is used")
    return checked_dac_code(int(value), name)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Configure channel bias and trim through EnvelopeV2."
    )
    parser.add_argument("-ip", "--ip", default="127.0.0.1")
    parser.add_argument("-port", "--port", type=int, default=9876)
    parser.add_argument(
        "-channel", "--channel", type=int, choices=range(40), required=True
    )
    parser.add_argument("-bias", "--bias", type=float, required=True)
    parser.add_argument(
        "-bias_control", "--bias-control", type=float, required=True
    )
    parser.add_argument("-trim", "--trim", type=int, required=True)
    parser.add_argument(
        "-set_as_DAC",
        "--set-as-dac",
        dest="set_as_dac",
        action="store_true",
        help="Interpret bias and bias-control inputs as DAC codes.",
    )
    parser.add_argument("-route", "--route", "-r", default="mezz/0")
    parser.add_argument(
        "--timeout-ms", "--timeout_ms", type=int, default=5000
    )
    parser.add_argument("--identity", default="configure-vbias-trim-v2")
    return parser


def require_success(label, response):
    state = "PASS" if response.success else "FAIL"
    print(f"[{state}] {label}: {response.message}")
    if not response.success:
        raise RuntimeError(f"{label} failed: {response.message}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        checked_dac_code(args.trim, "trim")
        if args.set_as_dac:
            bias_dac = direct_dac_code(args.bias, "bias")
            bias_control_dac = direct_dac_code(
                args.bias_control, "bias control"
            )
        else:
            bias_dac = checked_dac_code(
                bias_volts_to_dac(args.bias), "bias"
            )
            bias_control_dac = checked_dac_code(
                bias_control_volts_to_dac(args.bias_control),
                "bias control",
            )
    except ValueError as exc:
        parser.error(str(exc))

    afe = args.channel // 8

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
                pb_high.MT2_WRITE_VBIAS_CONTROL_REQ,
                pb_low.cmd_writeVbiasControl(
                    vBiasControlValue=bias_control_dac,
                    enable=True,
                ),
                pb_high.MT2_WRITE_VBIAS_CONTROL_RESP,
                pb_low.cmd_writeVbiasControl_response,
            )
            require_success(
                f"VBIAS control DAC={response.vBiasControlValue}", response
            )

            response = client.rpc(
                pb_high.MT2_WRITE_AFE_BIAS_SET_REQ,
                pb_low.cmd_writeAFEBiasSet(
                    afeBlock=afe,
                    biasValue=bias_dac,
                ),
                pb_high.MT2_WRITE_AFE_BIAS_SET_RESP,
                pb_low.cmd_writeAFEBiasSet_response,
            )
            require_success(
                f"AFE {afe} bias DAC={response.biasValue}", response
            )

            response = client.rpc(
                pb_high.MT2_WRITE_TRIM_CH_REQ,
                pb_low.cmd_writeTrim_singleChannel(
                    trimChannel=args.channel,
                    trimValue=args.trim,
                    trimGain=False,
                ),
                pb_high.MT2_WRITE_TRIM_CH_RESP,
                pb_low.cmd_writeTrim_singleChannel_response,
            )
            require_success(
                f"channel {args.channel} trim DAC={response.trimValue}",
                response,
            )
    except (RuntimeError, TimeoutError, zmq.ZMQError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
