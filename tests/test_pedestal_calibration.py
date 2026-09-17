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
    ADC_MAX,
    INITIAL_OFFSET,
    PEDESTAL_WAVEFORMS,
    _read_current_offsets,
    _measure_pedestals,
    _verify_configured_offsets,
    _write_offset,
    build_parser,
    calibrate_pedestals,
    calibrate_pedestals_auto,
    parse_channels,
    pedestal_levels,
)


class _SimulatedHardware:
    def __init__(self, transfer_functions):
        self.transfer_functions = transfer_functions
        self.offsets = {}
        self.writes = {channel: [] for channel in transfer_functions}
        self.measurements = []

    def write_offset(self, channel, offset):
        self.offsets[channel] = offset
        self.writes[channel].append(offset)

    def measure(self, channels):
        self.measurements.append(
            {channel: self.offsets[channel] for channel in channels}
        )
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


class _OffsetReadRequest:
    pass


class _OffsetReadResponse:
    pass


class _FakeLowProto:
    cmd_readOffset_allChannels = _OffsetReadRequest
    cmd_readOffset_allChannels_response = _OffsetReadResponse


class _OffsetReadClient:
    def rpc(self, request_type, request, response_type, response_class):
        self.request = request
        self.response_class = response_class
        response = _OffsetReadResponse()
        response.success = True
        response.message = "OK"
        response.offsetValues = [2000 + channel for channel in range(40)]
        return response


class _WriteOffsetRequest:
    def __init__(self, offsetChannel, offsetValue, offsetGain):
        self.offsetChannel = offsetChannel
        self.offsetValue = offsetValue
        self.offsetGain = offsetGain


class _WriteOffsetResponse:
    pass


class _StatefulLowProto:
    cmd_readOffset_allChannels = _OffsetReadRequest
    cmd_readOffset_allChannels_response = _OffsetReadResponse
    cmd_writeOFFSET_singleChannel = _WriteOffsetRequest
    cmd_writeOFFSET_singleChannel_response = _WriteOffsetResponse


class _StatefulHighProto:
    MT2_READ_OFFSET_ALL_CH_REQ = 200
    MT2_READ_OFFSET_ALL_CH_RESP = 201
    MT2_WRITE_OFFSET_CH_REQ = 202
    MT2_WRITE_OFFSET_CH_RESP = 203


class _StatefulOffsetClient:
    def __init__(self):
        self.offsets = [0] * 40

    def rpc(self, request_type, request, response_type, response_class):
        if request_type == _StatefulHighProto.MT2_WRITE_OFFSET_CH_REQ:
            if response_type != _StatefulHighProto.MT2_WRITE_OFFSET_CH_RESP:
                raise AssertionError("unexpected write response type")
            self.offsets[request.offsetChannel] = request.offsetValue
            response = _WriteOffsetResponse()
            response.success = True
            response.message = "OK"
            response.offsetValue = request.offsetValue
            return response
        if request_type == _StatefulHighProto.MT2_READ_OFFSET_ALL_CH_REQ:
            if response_type != _StatefulHighProto.MT2_READ_OFFSET_ALL_CH_RESP:
                raise AssertionError("unexpected read response type")
            response = _OffsetReadResponse()
            response.success = True
            response.message = "OK"
            response.offsetValues = list(self.offsets)
            return response
        raise AssertionError(f"unexpected request type {request_type}")


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
        self.assertEqual(args.max_iterations, 20)
        self.assertEqual(args.max_offset_change, 300)

    def test_cli_exposes_auto_and_clear_manual_option_names(self):
        parser = build_parser()
        auto_args = parser.parse_args(
            ["--auto", "-target_pedestal", "8000", "-L", "1024"]
        )
        self.assertTrue(auto_args.auto)
        self.assertIsNone(auto_args.max_iterations)
        self.assertIsNone(auto_args.max_offset_change)

        manual_args = build_parser().parse_args(
            [
                "-target_pedestal",
                "8000",
                "-L",
                "1024",
                "--max-iterations",
                "12",
                "--max-offset-change",
                "50",
            ]
        )
        self.assertEqual(manual_args.max_iterations, 12)
        self.assertEqual(manual_args.max_offset_change, 50)
        help_text = parser.format_help()
        self.assertIn("--max-offset-change", help_text)
        self.assertNotIn("max_iteration_offset", help_text)

    def test_cli_accepts_current_offset_flag_and_suggested_alias(self):
        for flag in (
            "--use-current-offset",
            "--use_current_offset",
            "--use_init_current_pedestal",
        ):
            args = build_parser().parse_args(
                [flag, "-target_pedestal", "8000", "-L", "64"]
            )
            self.assertTrue(args.use_current_offset)

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

    def test_reads_current_offsets_for_selected_channels(self):
        class HighProto:
            MT2_READ_OFFSET_ALL_CH_REQ = 200
            MT2_READ_OFFSET_ALL_CH_RESP = 201

        client = _OffsetReadClient()
        offsets = _read_current_offsets(
            HighProto, _FakeLowProto, client, [0, 7, 33]
        )

        self.assertEqual(offsets, {0: 2000, 7: 2007, 33: 2033})
        self.assertIsInstance(client.request, _OffsetReadRequest)
        self.assertIs(client.response_class, _OffsetReadResponse)

    def test_configures_and_reads_back_one_or_multiple_channel_offsets(self):
        cases = (
            {7: 2210},
            {1: 2101, 8: 2208, 33: 2233},
        )
        for expected in cases:
            with self.subTest(channels=list(expected)):
                client = _StatefulOffsetClient()
                for channel, offset in expected.items():
                    _write_offset(
                        _StatefulHighProto,
                        _StatefulLowProto,
                        client,
                        channel,
                        offset,
                    )

                actual = _verify_configured_offsets(
                    _StatefulHighProto,
                    _StatefulLowProto,
                    client,
                    expected,
                )

                self.assertEqual(actual, expected)
                for channel, offset in expected.items():
                    self.assertEqual(client.offsets[channel], offset)

    def test_final_offset_verification_rejects_a_readback_mismatch(self):
        client = _StatefulOffsetClient()
        client.offsets[5] = 2000

        with self.assertRaisesRegex(RuntimeError, "ch5: expected 2100, read 2000"):
            _verify_configured_offsets(
                _StatefulHighProto,
                _StatefulLowProto,
                client,
                {5: 2100},
            )

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

    def test_manual_mode_can_measure_current_offset_without_initial_write(self):
        hardware = _SimulatedHardware({0: lambda offset: 4.0 * offset})
        hardware.offsets[0] = 1800

        result = calibrate_pedestals(
            channels=[0],
            target=7200,
            method="bisection",
            max_iterations=12,
            max_offset_step=400,
            tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
            initial_offsets={0: 1800},
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(hardware.measurements[0], {0: 1800})
        self.assertEqual(hardware.writes[0], [])

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

    def test_auto_mode_derives_sensitivity_tolerance_and_offset_change(self):
        hardware = _SimulatedHardware(
            {33: lambda offset: 20.0 * offset - 36509.0}
        )

        result = calibrate_pedestals_auto(
            channels=[33],
            target=8000,
            method="regula_falsi",
            minimum_tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(result.offset, 2225)
        self.assertEqual(result.pedestal, 7991)
        self.assertEqual(result.sensitivity, 20)
        self.assertEqual(result.tolerance, 10)
        self.assertEqual(hardware.writes[33][:2], [2275, 2274])
        self.assertGreater(
            abs(hardware.writes[33][2] - hardware.writes[33][1]), 1
        )

    def test_auto_mode_starts_from_current_offset_without_rewriting_it(self):
        hardware = _SimulatedHardware({0: lambda offset: 4.0 * offset})
        hardware.offsets[0] = 2200

        result = calibrate_pedestals_auto(
            channels=[0],
            target=8800,
            method="regula_falsi",
            minimum_tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
            initial_offsets={0: 2200},
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(hardware.measurements[0], {0: 2200})
        self.assertEqual(hardware.writes[0][0], 2201)
        self.assertNotIn(INITIAL_OFFSET, hardware.writes[0])

    def test_auto_mode_expands_probe_out_of_low_saturation(self):
        hardware = _SimulatedHardware(
            {0: lambda offset: max(0.0, 10.0 * (offset - 2300))}
        )

        result = calibrate_pedestals_auto(
            channels=[0],
            target=100,
            method="regula_falsi",
            minimum_tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertTrue(result.converged)
        self.assertEqual(result.offset, 2310)
        self.assertEqual(result.pedestal, 100)
        self.assertIn(2307, hardware.writes[0])

    def test_auto_mode_handles_both_14_bit_rails(self):
        low_hardware = _SimulatedHardware(
            {0: lambda offset: max(0.0, 10.0 * (offset - INITIAL_OFFSET))}
        )
        low_result = calibrate_pedestals_auto(
            channels=[0],
            target=0,
            method="bisection",
            minimum_tolerance=1.0,
            write_offset=low_hardware.write_offset,
            measure_pedestals=low_hardware.measure,
            report=None,
        )[0]

        high_hardware = _SimulatedHardware(
            {
                0: lambda offset: min(
                    float(ADC_MAX),
                    ADC_MAX + 10.0 * (offset - INITIAL_OFFSET),
                )
            }
        )
        high_result = calibrate_pedestals_auto(
            channels=[0],
            target=ADC_MAX,
            method="bisection",
            minimum_tolerance=1.0,
            write_offset=high_hardware.write_offset,
            measure_pedestals=high_hardware.measure,
            report=None,
        )[0]

        self.assertTrue(low_result.converged)
        self.assertEqual(low_result.pedestal, 0)
        self.assertTrue(high_result.converged)
        self.assertEqual(high_result.pedestal, ADC_MAX)

    def test_auto_mode_accepts_target_on_a_fully_saturated_rail(self):
        hardware = _SimulatedHardware({0: lambda offset: 0.0})

        result = calibrate_pedestals_auto(
            channels=[0],
            target=0,
            method="regula_falsi",
            minimum_tolerance=1.0,
            write_offset=hardware.write_offset,
            measure_pedestals=hardware.measure,
            report=None,
        )[0]

        self.assertTrue(result.converged)
        self.assertIsNone(result.sensitivity)
        self.assertIn("ADC rail", result.reason)
        self.assertEqual(hardware.offsets[0], INITIAL_OFFSET)

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
