#!/usr/bin/env python3

from pathlib import Path
import sys
import types
import unittest


class _ZmqError(Exception):
    pass


sys.modules["zmq"] = types.SimpleNamespace(
    Again=_ZmqError,
    ZMQError=_ZmqError,
    DEALER=1,
    IDENTITY=2,
    LINGER=3,
    RCVTIMEO=4,
    SNDTIMEO=5,
    RCVMORE=6,
)


CLIENT_DIR = Path(__file__).resolve().parents[1] / "client"
sys.path.insert(0, str(CLIENT_DIR))

from protobuf_read_configuration import (  # noqa: E402
    READ_OPTIONS,
    build_parser,
    read_configuration,
    resolve_selection,
)


class _EmptyRequest:
    pass


class _AfeRequest:
    def __init__(self, afeBlock):
        self.afeBlock = afeBlock


class _Response:
    pass


class _FakeHighProto:
    MT2_READ_OFFSET_ALL_CH_REQ = 100
    MT2_READ_OFFSET_ALL_CH_RESP = 101
    MT2_READ_TRIM_ALL_CH_REQ = 102
    MT2_READ_TRIM_ALL_CH_RESP = 103
    MT2_READ_AFE_VGAIN_REQ = 104
    MT2_READ_AFE_VGAIN_RESP = 105
    MT2_READ_AFE_BIAS_SET_REQ = 106
    MT2_READ_AFE_BIAS_SET_RESP = 107
    MT2_READ_VBIAS_CONTROL_REQ = 108
    MT2_READ_VBIAS_CONTROL_RESP = 109


class _FakeLowProto:
    cmd_readOffset_allChannels = _EmptyRequest
    cmd_readOffset_allChannels_response = _Response
    cmd_readTrim_allChannels = _EmptyRequest
    cmd_readTrim_allChannels_response = _Response
    cmd_readAFEVgain = _AfeRequest
    cmd_readAFEVgain_response = _Response
    cmd_readAFEBiasSet = _AfeRequest
    cmd_readAFEBiasSet_response = _Response
    cmd_readVbiasControl = _EmptyRequest
    cmd_readVbiasControl_response = _Response


class _FakeClient:
    def __init__(self, *, failure_type=None, short_offsets=False):
        self.failure_type = failure_type
        self.short_offsets = short_offsets
        self.calls = []

    def rpc(self, request_type, request, response_type, response_class):
        self.calls.append((request_type, request, response_type, response_class))
        response = _Response()
        response.success = request_type != self.failure_type
        response.message = "simulated failure" if not response.success else "OK"

        if request_type == _FakeHighProto.MT2_READ_OFFSET_ALL_CH_REQ:
            count = 39 if self.short_offsets else 40
            response.offsetValues = [2000 + channel for channel in range(count)]
        elif request_type == _FakeHighProto.MT2_READ_TRIM_ALL_CH_REQ:
            response.trimValues = [100 + channel for channel in range(40)]
        elif request_type == _FakeHighProto.MT2_READ_AFE_VGAIN_REQ:
            response.afeBlock = request.afeBlock
            response.vgainValue = 1000 + request.afeBlock
        elif request_type == _FakeHighProto.MT2_READ_AFE_BIAS_SET_REQ:
            response.afeBlock = request.afeBlock
            response.biasValue = 500 + request.afeBlock
        elif request_type == _FakeHighProto.MT2_READ_VBIAS_CONTROL_REQ:
            response.vBiasControlValue = 77
        else:
            raise AssertionError(f"unexpected request type {request_type}")
        return response


class SelectionTests(unittest.TestCase):
    def test_no_selector_reads_everything(self):
        channels, afes = resolve_selection(None, None)
        self.assertEqual(channels, list(range(40)))
        self.assertEqual(afes, list(range(5)))

    def test_one_or_multiple_channels_select_their_afes(self):
        channels, afes = resolve_selection(["33"], None)
        self.assertEqual(channels, [33])
        self.assertEqual(afes, [4])

        channels, afes = resolve_selection(["1,9", "34"], None)
        self.assertEqual(channels, [1, 9, 34])
        self.assertEqual(afes, [0, 1, 4])

    def test_afe_selector_expands_to_its_channels(self):
        channels, afes = resolve_selection(None, ["1", "3"])
        self.assertEqual(channels, list(range(8, 16)) + list(range(24, 32)))
        self.assertEqual(afes, [1, 3])

    def test_channel_afe_is_added_to_explicit_afe_list(self):
        channels, afes = resolve_selection(["33"], ["0"])
        self.assertEqual(channels, [33])
        self.assertEqual(afes, [0, 4])

    def test_invalid_selector_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "channel out of range"):
            resolve_selection(["40"], None)
        with self.assertRaisesRegex(ValueError, "AFE out of range"):
            resolve_selection(None, ["5"])

    def test_independent_read_flags_can_be_combined(self):
        args = build_parser().parse_args(["--offset", "--bias-control"])
        requested = {
            option for option in READ_OPTIONS if getattr(args, option)
        }
        self.assertEqual(requested, {"offset", "bias_control"})


class ReadConfigurationTests(unittest.TestCase):
    def test_reads_one_channel_and_its_afe(self):
        client = _FakeClient()
        snapshot = read_configuration(
            _FakeHighProto, _FakeLowProto, client, [33], [4]
        )

        self.assertEqual(
            snapshot["afes"], [{"afe": 4, "bias": 504, "vgain": 1004}]
        )
        self.assertEqual(
            snapshot["channels"],
            [
                {
                    "channel": 33,
                    "afe": 4,
                    "offset": 2033,
                    "trim": 133,
                    "bias": 504,
                }
            ],
        )
        self.assertEqual(snapshot["bias_control"], 77)
        self.assertEqual(len(client.calls), 5)

    def test_reads_multiple_channels_and_afes(self):
        client = _FakeClient()
        snapshot = read_configuration(
            _FakeHighProto, _FakeLowProto, client, [1, 9, 34], [0, 1, 4]
        )

        self.assertEqual([item["afe"] for item in snapshot["afes"]], [0, 1, 4])
        self.assertEqual(
            snapshot["channels"],
            [
                {"channel": 1, "afe": 0, "offset": 2001, "trim": 101, "bias": 500},
                {"channel": 9, "afe": 1, "offset": 2009, "trim": 109, "bias": 501},
                {"channel": 34, "afe": 4, "offset": 2034, "trim": 134, "bias": 504},
            ],
        )
        self.assertEqual(snapshot["bias_control"], 77)
        self.assertEqual(len(client.calls), 9)

    def test_offset_can_be_read_independently(self):
        client = _FakeClient()
        snapshot = read_configuration(
            _FakeHighProto,
            _FakeLowProto,
            client,
            [33],
            [4],
            {"offset"},
        )

        self.assertEqual(
            snapshot,
            {"channels": [{"channel": 33, "afe": 4, "offset": 2033}]},
        )
        self.assertEqual(
            [call[0] for call in client.calls],
            [_FakeHighProto.MT2_READ_OFFSET_ALL_CH_REQ],
        )

    def test_bias_control_can_be_read_independently(self):
        client = _FakeClient()
        snapshot = read_configuration(
            _FakeHighProto,
            _FakeLowProto,
            client,
            list(range(40)),
            list(range(5)),
            {"bias_control"},
        )

        self.assertEqual(snapshot, {"bias_control": 77})
        self.assertEqual(
            [call[0] for call in client.calls],
            [_FakeHighProto.MT2_READ_VBIAS_CONTROL_REQ],
        )

    def test_trim_and_vgain_only_issue_their_rpcs(self):
        client = _FakeClient()
        snapshot = read_configuration(
            _FakeHighProto,
            _FakeLowProto,
            client,
            [9],
            [1],
            {"trim", "vgain"},
        )

        self.assertEqual(snapshot["afes"], [{"afe": 1, "vgain": 1001}])
        self.assertEqual(
            snapshot["channels"],
            [{"channel": 9, "afe": 1, "trim": 109}],
        )
        self.assertEqual(
            [call[0] for call in client.calls],
            [
                _FakeHighProto.MT2_READ_TRIM_ALL_CH_REQ,
                _FakeHighProto.MT2_READ_AFE_VGAIN_REQ,
            ],
        )

    def test_failed_rpc_is_rejected(self):
        client = _FakeClient(
            failure_type=_FakeHighProto.MT2_READ_AFE_BIAS_SET_REQ
        )
        with self.assertRaisesRegex(RuntimeError, "read BIAS for AFE 0 failed"):
            read_configuration(
                _FakeHighProto, _FakeLowProto, client, [0], [0]
            )

    def test_incomplete_channel_response_is_rejected(self):
        client = _FakeClient(short_offsets=True)
        with self.assertRaisesRegex(RuntimeError, "returned 39 values"):
            read_configuration(
                _FakeHighProto, _FakeLowProto, client, [0], [0]
            )


if __name__ == "__main__":
    unittest.main()
