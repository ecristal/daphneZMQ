"""Shared CLI and V2 RPC helpers for the global spybuffer trigger source."""

import sys


TRIGGER_SOURCE_CHOICES = ("software", "external", "timing", "all")

_SOURCE_ENUM_NAMES = {
    "software": "SPY_TRIGGER_SOURCE_SOFTWARE",
    "external": "SPY_TRIGGER_SOURCE_EXTERNAL",
    "timing": "SPY_TRIGGER_SOURCE_TIMING",
    "all": "SPY_TRIGGER_SOURCE_LEGACY_ALL",
}


def add_trigger_source_arguments(parser, default="external"):
    parser.add_argument(
        "-trigger_source",
        "--trigger-source",
        choices=TRIGGER_SOURCE_CHOICES,
        default=None,
        help=(
            "Global spybuffer trigger source: software, external, timing, or "
            f"all (default: {default})."
        ),
    )
    parser.add_argument(
        "-software_trigger",
        "--software-trigger",
        action="store_true",
        dest="legacy_software_trigger",
        help="Deprecated alias for -trigger_source software.",
    )
    parser.set_defaults(trigger_source_default=default)


def resolve_trigger_source(parser, args):
    source = args.trigger_source
    if args.legacy_software_trigger:
        if source is not None and source != "software":
            parser.error(
                "-software_trigger conflicts with "
                f"-trigger_source {source}"
            )
        source = "software"
        print(
            "warning: -software_trigger is deprecated; use "
            "-trigger_source software",
            file=sys.stderr,
        )

    if source is None:
        source = args.trigger_source_default

    args.trigger_source = source
    # DumpSpyBuffers keeps this field for deciding whether the server should
    # issue one software trigger per requested waveform.
    args.software_trigger = source == "software"
    return source


def configure_trigger_source(pb, send_v2_request, source):
    """Write and read back SOURCE using a V2 request callback.

    ``send_v2_request`` receives ``(message_type, serialized_payload)`` and
    returns ``(response_message_type, serialized_payload)``.
    """
    enum_name = _SOURCE_ENUM_NAMES[source]
    required = (
        enum_name,
        "WriteSpyBufferTriggerSourceRequest",
        "WriteSpyBufferTriggerSourceResponse",
        "ReadSpyBufferTriggerSourceRequest",
        "ReadSpyBufferTriggerSourceResponse",
        "MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ",
        "MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_RESP",
        "MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ",
        "MT2_READ_SPYBUFFER_TRIGGER_SOURCE_RESP",
    )
    missing = [name for name in required if not hasattr(pb, name)]
    if missing:
        raise RuntimeError(
            "Python protobuf bindings do not contain the spybuffer trigger "
            "source RPCs; rebuild the protobuf bindings. Missing: "
            + ", ".join(missing)
        )

    expected_source = getattr(pb, enum_name)
    write_request = pb.WriteSpyBufferTriggerSourceRequest()
    write_request.source = expected_source
    response_type, response_payload = send_v2_request(
        pb.MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ,
        write_request.SerializeToString(),
    )
    if response_type != pb.MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_RESP:
        raise RuntimeError(
            f"Unexpected trigger-source write response type {response_type}"
        )
    write_response = pb.WriteSpyBufferTriggerSourceResponse()
    write_response.ParseFromString(response_payload)
    if not write_response.success:
        raise RuntimeError(
            "Could not configure spybuffer trigger source: "
            + write_response.message
        )
    if write_response.source != expected_source:
        raise RuntimeError(
            "Trigger-source write readback mismatch: "
            f"expected {expected_source}, got {write_response.source}"
        )

    read_request = pb.ReadSpyBufferTriggerSourceRequest()
    response_type, response_payload = send_v2_request(
        pb.MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ,
        read_request.SerializeToString(),
    )
    if response_type != pb.MT2_READ_SPYBUFFER_TRIGGER_SOURCE_RESP:
        raise RuntimeError(
            f"Unexpected trigger-source read response type {response_type}"
        )
    read_response = pb.ReadSpyBufferTriggerSourceResponse()
    read_response.ParseFromString(response_payload)
    if not read_response.success:
        raise RuntimeError(
            "Could not read spybuffer trigger source: " + read_response.message
        )
    if read_response.source != expected_source:
        raise RuntimeError(
            "Trigger-source verification mismatch: "
            f"expected {expected_source}, got {read_response.source}"
        )

    return source
