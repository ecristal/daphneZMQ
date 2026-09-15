#!/usr/bin/env python3

from pathlib import Path
import sys
import types
import unittest


class _Again(Exception):
    pass


class _ZmqError(Exception):
    pass


sys.modules["zmq"] = types.SimpleNamespace(
    Again=_Again,
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

from protobuf_configure_pedestal_level import (  # noqa: E402
    INITIAL_OFFSET,
    PEDESTAL_WAVEFORMS,
    _measure_pedestals,
    build_parser,
    calibrate_pedestals,
    parse_channels,
    pedestal_levels,
)


class _SimulatedHardware:
    def __init__(self, transfer_functions):
        self.transfer_functions = transfer_functions
        self.offsets = {}
        self.writes = {channel: [] for channel in transfer_functions}

    def write_offset(self, channel, offset):
        self.offsets[channel] = offset
        self.writes[channel].append(offset)

    def measure(self, channels):
        return {
            channel: self.transfer_functions[channel](self.offsets[channel])
            for channel in channels
        }


class _DumpRequest:
    def __init__(self):
        self.channelList = []
        self.numberOfWaveforms = 0
        self.numberOfSamples = 0
        self.softwareTrigger = False


class _DumpResponse:
    pass


class _FakeHighProto:
    MT2_DUMP_SPYBUFFER_REQ = 100
    MT2_DUMP_SPYBUFFER_RESP = 101
    DumpSpyBuffersRequest = _DumpRequest
    DumpSpyBuffersResponse = _DumpResponse


class _AcquisitionClient:
    def rpc(self, request_type, request, response_type, response_class):
        if request_type != _FakeHighProto.MT2_DUMP_SPYBUFFER_REQ:
            raise AssertionError("unexpected request type")
        if response_type != _FakeHighProto.MT2_DUMP_SPYBUFFER_RESP:
            raise AssertionError("unexpected response type")
        if response_class is not _DumpResponse:
            raise AssertionError("unexpected response class")
        if request.numberOfWaveforms != PEDESTAL_WAVEFORMS:
            raise AssertionError("client did not request exactly 500 waveforms")
        if not request.softwareTrigger:
            raise AssertionError("client did not request software triggers")

        response = _DumpResponse()
        response.success = True
        response.message = "OK"
        response.channelList = list(request.channelList)
        response.numberOfWaveforms = request.numberOfWaveforms
        response.numberOfSamples = request.numberOfSamples
        response.softwareTrigger = request.softwareTrigger
        one_waveform = [100, 100, 200, 300, 400, 400]
        response.data = one_waveform * PEDESTAL_WAVEFORMS
        return response


class PedestalCalibrationTests(unittest.TestCase):
    def test_cli_accepts_requested_calibration_parameters(self):
        args = build_parser().parse_args(
            [
                "-channel",
                "2",
                "7",
                "-target_pedestal",
                "6000",
                "-method",
                "regula-falsi",
                "-max_iteration_steps",
                "20",
                "-max_iteration_offset",
                "300",
                "-L",
                "64",
            ]
        )
        self.assertEqual(args.channel, ["2", "7"])
        self.assertEqual(args.target_pedestal, 6000)
        self.assertEqual(args.method, "regula_falsi")
        self.assertEqual(args.max_iteration_steps, 20)
        self.assertEqual(args.max_iteration_offset, 300)

    def test_parses_one_many_comma_separated_and_all_channels(self):
        self.assertEqual(parse_channels(None, False), [0])
        self.assertEqual(parse_channels(["1", "3,5", "3"], False), [1, 3, 5])
        self.assertEqual(parse_channels(None, True), list(range(40)))
        with self.assertRaisesRegex(ValueError, "out of range"):
            parse_channels(["40"], False)

    def test_pedestal_is_mode_of_the_mean_waveform(self):
        waves = [
            [
                [101, 101, 201, 100] if index == 0 else [100, 100, 200, 100],
                [300, 400, 400, 500],
            ]
            for index in range(PEDESTAL_WAVEFORMS)
        ]

        levels = pedestal_levels(waves)

        self.assertAlmostEqual(levels[0], 100.002)
        self.assertEqual(levels[1], 400.0)

    def test_rpc_acquisition_uses_500_software_triggered_waveforms(self):
        levels = _measure_pedestals(
            _FakeHighProto, _AcquisitionClient(), [2, 7], samples=3
        )
        self.assertEqual(levels, {2: 100.0, 7: 400.0})

    def test_bisection_converges_and_obeys_maximum_step(self):
        hardware = _SimulatedHardware({0: lambda offset: 4.0 * offset})

        result = calibrate_pedestals(
            channels=[0],
            target=6000,
            method="bisection",
            max_iterations=12,
            max_offset_step=400,
            tolerance=0.1,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(result.offset, 1500)
        self.assertEqual(result.pedestal, 6000)
        self.assertEqual(hardware.writes[0][0], INITIAL_OFFSET)
        for previous, current in zip(hardware.writes[0], hardware.writes[0][1:]):
            self.assertLessEqual(abs(current - previous), 400)

    def test_regula_falsi_calibrates_channels_independently(self):
        hardware = _SimulatedHardware(
            {
                2: lambda offset: 4.0 * offset,
                7: lambda offset: 2.0 * offset + 2000,
            }
        )

        results = calibrate_pedestals(
            channels=[2, 7],
            target=6000,
            method="regula_falsi",
            max_iterations=12,
            max_offset_step=512,
            tolerance=0.1,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )

        self.assertEqual([result.channel for result in results], [2, 7])
        self.assertEqual([result.offset for result in results], [1500, 2000])
        self.assertTrue(all(result.converged for result in results))

    def test_iteration_limit_does_not_write_an_unmeasured_candidate(self):
        hardware = _SimulatedHardware({0: lambda offset: 4.0 * offset})

        result = calibrate_pedestals(
            channels=[0],
            target=6000,
            method="bisection",
            max_iterations=1,
            max_offset_step=400,
            tolerance=0.1,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertFalse(result.converged)
        self.assertEqual(result.reason, "maximum iterations reached")
        self.assertEqual(hardware.writes[0], [INITIAL_OFFSET])

    def test_reports_unreachable_saturated_target_and_keeps_best_offset(self):
        hardware = _SimulatedHardware(
            {0: lambda offset: min(8000.0, 2.0 * offset)}
        )

        result = calibrate_pedestals(
            channels=[0],
            target=12000,
            method="regula_falsi",
            max_iterations=10,
            max_offset_step=512,
            tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertFalse(result.converged)
        self.assertEqual(result.pedestal, 8000)
        self.assertIn("upper offset limit", result.reason)
        self.assertEqual(hardware.offsets[0], result.offset)


if __name__ == "__main__":
    unittest.main()
