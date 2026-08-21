import argparse
import contextlib
import io
from pathlib import Path
import sys
import unittest

CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from trigger_source import (  # noqa: E402
    add_trigger_source_arguments,
    configure_trigger_source,
    resolve_trigger_source,
)


class _Request:
    def __init__(self):
        self.source = 0

    def SerializeToString(self):
        return bytes((self.source,))


class _EmptyRequest:
    def SerializeToString(self):
        return b""


class _Response:
    def __init__(self):
        self.success = False
        self.message = ""
        self.source = 0

    def ParseFromString(self, payload):
        self.success = bool(payload[0])
        self.source = payload[1]
        self.message = payload[2:].decode()


class _FakeProto:
    SPY_TRIGGER_SOURCE_SOFTWARE = 0
    SPY_TRIGGER_SOURCE_EXTERNAL = 1
    SPY_TRIGGER_SOURCE_TIMING = 2
    SPY_TRIGGER_SOURCE_LEGACY_ALL = 3

    MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ = 326
    MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_RESP = 327
    MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ = 328
    MT2_READ_SPYBUFFER_TRIGGER_SOURCE_RESP = 329

    WriteSpyBufferTriggerSourceRequest = _Request
    WriteSpyBufferTriggerSourceResponse = _Response
    ReadSpyBufferTriggerSourceRequest = _EmptyRequest
    ReadSpyBufferTriggerSourceResponse = _Response


def _parser():
    parser = argparse.ArgumentParser()
    add_trigger_source_arguments(parser)
    return parser


class TriggerSourceClientTests(unittest.TestCase):
    def test_default_is_external(self):
        parser = _parser()
        args = parser.parse_args([])
        self.assertEqual(resolve_trigger_source(parser, args), "external")
        self.assertFalse(args.software_trigger)

    def test_software_alias_is_preserved(self):
        parser = _parser()
        args = parser.parse_args(["-software_trigger"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(resolve_trigger_source(parser, args), "software")
        self.assertTrue(args.software_trigger)

    def test_conflicting_alias_is_rejected(self):
        parser = _parser()
        args = parser.parse_args(
            ["-software_trigger", "-trigger_source", "timing"]
        )
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            resolve_trigger_source(parser, args)

    def test_all_sources_are_written_and_verified(self):
        hardware = {"source": 3}

        def send(message_type, payload):
            if message_type == _FakeProto.MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ:
                hardware["source"] = payload[0]
                return (
                    _FakeProto.MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_RESP,
                    bytes((1, hardware["source"])) + b"OK",
                )
            self.assertEqual(
                message_type,
                _FakeProto.MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ,
            )
            return (
                _FakeProto.MT2_READ_SPYBUFFER_TRIGGER_SOURCE_RESP,
                bytes((1, hardware["source"])) + b"OK",
            )

        for source, expected in (
            ("software", 0),
            ("external", 1),
            ("timing", 2),
            ("all", 3),
        ):
            self.assertEqual(
                configure_trigger_source(_FakeProto, send, source),
                source,
            )
            self.assertEqual(hardware["source"], expected)


if __name__ == "__main__":
    unittest.main()
