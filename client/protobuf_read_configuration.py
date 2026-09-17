#!/usr/bin/env python3
"""Read the configured OFFSET, TRIM, BIAS, and VGAIN values."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

import zmq

from protobuf_loader import load_protobuf_modules
from v2_client import V2Client


CHANNEL_COUNT = 40
AFE_COUNT = 5
CHANNELS_PER_AFE = CHANNEL_COUNT // AFE_COUNT
READ_OPTIONS = ("offset", "trim", "bias", "vgain", "bias_control")


def parse_indices(
    tokens: Optional[Sequence[str]], *, count: int, name: str
) -> Optional[list[int]]:
    """Parse space- or comma-separated channel/AFE selectors."""
    if tokens is None:
        return None

    values = []
    for token in tokens:
        for item in token.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                value = int(item)
            except ValueError as exc:
                raise ValueError(f"invalid {name} {item!r}") from exc
            if not 0 <= value < count:
                raise ValueError(
                    f"{name} out of range 0..{count - 1}: {value}"
                )
            if value not in values:
                values.append(value)

    if not values:
        raise ValueError(f"at least one {name} is required")
    return values


def resolve_selection(
    channel_tokens: Optional[Sequence[str]],
    afe_tokens: Optional[Sequence[str]],
) -> tuple[list[int], list[int]]:
    """Resolve selectors and include the AFE needed by every channel."""
    channels = parse_indices(
        channel_tokens, count=CHANNEL_COUNT, name="channel"
    )
    afes = parse_indices(afe_tokens, count=AFE_COUNT, name="AFE")

    if channels is None and afes is None:
        return list(range(CHANNEL_COUNT)), list(range(AFE_COUNT))
    if channels is None:
        channels = [
            channel
            for afe in afes
            for channel in range(
                afe * CHANNELS_PER_AFE, (afe + 1) * CHANNELS_PER_AFE
            )
        ]
    if afes is None:
        afes = []

    # Bias and VGAIN are AFE-wide, so every selected channel requires its AFE.
    afes = list(afes)
    for channel in channels:
        afe = channel // CHANNELS_PER_AFE
        if afe not in afes:
            afes.append(afe)

    return sorted(channels), sorted(afes)


def _rpc(
    client,
    request_type,
    request,
    response_type,
    response_class,
    label: str,
):
    response = client.rpc(
        request_type, request, response_type, response_class
    )
    if not getattr(response, "success", False):
        message = getattr(response, "message", "").strip()
        raise RuntimeError(f"{label} failed: {message or 'unknown server error'}")
    return response


def _channel_values(response, field: str, label: str) -> list[int]:
    values = list(getattr(response, field, []))
    if len(values) != CHANNEL_COUNT:
        raise RuntimeError(
            f"{label} returned {len(values)} values; expected {CHANNEL_COUNT}"
        )
    return values


def read_configuration(
    pb_high,
    pb_low,
    client,
    channels,
    afes,
    requested: Optional[set[str]] = None,
) -> dict:
    """Read and return a filtered front-end configuration snapshot."""
    requested = set(READ_OPTIONS if requested is None else requested)
    unknown = requested.difference(READ_OPTIONS)
    if unknown:
        raise ValueError(f"unknown read option(s): {', '.join(sorted(unknown))}")

    offsets = None
    if "offset" in requested:
        offset_response = _rpc(
            client,
            pb_high.MT2_READ_OFFSET_ALL_CH_REQ,
            pb_low.cmd_readOffset_allChannels(),
            pb_high.MT2_READ_OFFSET_ALL_CH_RESP,
            pb_low.cmd_readOffset_allChannels_response,
            "read all channel OFFSETs",
        )
        offsets = _channel_values(
            offset_response, "offsetValues", "OFFSET readback"
        )

    trims = None
    if "trim" in requested:
        trim_response = _rpc(
            client,
            pb_high.MT2_READ_TRIM_ALL_CH_REQ,
            pb_low.cmd_readTrim_allChannels(),
            pb_high.MT2_READ_TRIM_ALL_CH_RESP,
            pb_low.cmd_readTrim_allChannels_response,
            "read all channel TRIMs",
        )
        trims = _channel_values(
            trim_response, "trimValues", "TRIM readback"
        )

    afe_entries = []
    biases = {}
    for afe in (
        afes if requested.intersection(("bias", "vgain")) else []
    ):
        afe_entry = {"afe": afe}
        responses = []
        if "vgain" in requested:
            vgain_response = _rpc(
                client,
                pb_high.MT2_READ_AFE_VGAIN_REQ,
                pb_low.cmd_readAFEVgain(afeBlock=afe),
                pb_high.MT2_READ_AFE_VGAIN_RESP,
                pb_low.cmd_readAFEVgain_response,
                f"read VGAIN for AFE {afe}",
            )
            responses.append((vgain_response, "VGAIN"))
            afe_entry["vgain"] = int(vgain_response.vgainValue)
        if "bias" in requested:
            bias_response = _rpc(
                client,
                pb_high.MT2_READ_AFE_BIAS_SET_REQ,
                pb_low.cmd_readAFEBiasSet(afeBlock=afe),
                pb_high.MT2_READ_AFE_BIAS_SET_RESP,
                pb_low.cmd_readAFEBiasSet_response,
                f"read BIAS for AFE {afe}",
            )
            responses.append((bias_response, "BIAS"))
            bias = int(bias_response.biasValue)
            biases[afe] = bias
            afe_entry["bias"] = bias

        for response, label in responses:
            returned_afe = getattr(response, "afeBlock", afe)
            if returned_afe != afe:
                raise RuntimeError(
                    f"{label} response identified AFE {returned_afe}; "
                    f"expected {afe}"
                )

        afe_entries.append(afe_entry)

    channel_entries = []
    channel_reads = requested.intersection(("offset", "trim", "bias"))
    for channel in (channels if channel_reads else []):
        afe = channel // CHANNELS_PER_AFE
        entry = {"channel": channel, "afe": afe}
        if offsets is not None:
            entry["offset"] = int(offsets[channel])
        if trims is not None:
            entry["trim"] = int(trims[channel])
        if "bias" in requested:
            # BIAS is not independently configured per channel. This is the
            # common value inherited from the channel's AFE.
            entry["bias"] = biases[afe]
        channel_entries.append(entry)

    snapshot = {}
    if "bias" in requested:
        snapshot["bias_scope"] = (
            "afe (shared by 8 channels; per-channel adjustment is trim)"
        )
    if afe_entries:
        snapshot["afes"] = afe_entries
    if channel_entries:
        snapshot["channels"] = channel_entries
    if "bias_control" in requested:
        bias_control_response = _rpc(
            client,
            pb_high.MT2_READ_VBIAS_CONTROL_REQ,
            pb_low.cmd_readVbiasControl(),
            pb_high.MT2_READ_VBIAS_CONTROL_RESP,
            pb_low.cmd_readVbiasControl_response,
            "read BIAS control",
        )
        snapshot["bias_control"] = int(
            bias_control_response.vBiasControlValue
        )

    return snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read configured OFFSET and TRIM values by channel, and BIAS "
            "and VGAIN values by AFE. This client performs no writes."
        )
    )
    parser.add_argument("-ip", "--ip", default="127.0.0.1")
    parser.add_argument("-port", "--port", type=int, default=40001)
    parser.add_argument(
        "-channel",
        "--channel",
        "-channel_list",
        "--channel-list",
        dest="channels",
        nargs="+",
        help=(
            "One or more channels, space- or comma-separated. If omitted, "
            "channels are derived from --afe, or all 40 are read."
        ),
    )
    parser.add_argument(
        "-afe",
        "--afe",
        "-afe_list",
        "--afe-list",
        dest="afes",
        nargs="+",
        help=(
            "One or more AFEs, space- or comma-separated. AFEs containing "
            "selected channels are always included."
        ),
    )
    parser.add_argument("-route", "--route", "-r", default="mezz/0")
    parser.add_argument(
        "--timeout-ms", "--timeout_ms", type=int, default=5000
    )
    parser.add_argument(
        "--identity", default="protobuf-read-configuration"
    )
    parser.add_argument(
        "--compact", action="store_true", help="Print compact JSON."
    )
    reads = parser.add_argument_group(
        "independent read selection",
        "If none is specified, every configuration is read.",
    )
    reads.add_argument(
        "--offset", "--read-offset", action="store_true", help="Read OFFSET."
    )
    reads.add_argument(
        "--trim", "--read-trim", action="store_true", help="Read TRIM."
    )
    reads.add_argument(
        "--bias", "--read-bias", action="store_true", help="Read AFE BIAS."
    )
    reads.add_argument(
        "--vgain", "--read-vgain", action="store_true", help="Read VGAIN."
    )
    reads.add_argument(
        "--bias-control",
        "--bias_control",
        "--read-bias-control",
        action="store_true",
        help="Read the global BIAS control configuration.",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        channels, afes = resolve_selection(args.channels, args.afes)
        requested = {
            option for option in READ_OPTIONS if getattr(args, option)
        }
        if not requested:
            requested = set(READ_OPTIONS)
        pb_high, pb_low = load_protobuf_modules()
        with V2Client(
            pb_high,
            args.ip,
            args.port,
            route=args.route,
            timeout_ms=args.timeout_ms,
            identity=args.identity,
        ) as client:
            snapshot = read_configuration(
                pb_high, pb_low, client, channels, afes, requested
            )
    except (ValueError, RuntimeError, TimeoutError, zmq.ZMQError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(snapshot, indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
