#!/usr/bin/env python3
"""Hardware smoke test for the global spybuffer trigger-source selector."""

import argparse
import os
import random
import time
import uuid

import zmq

from protobuf_loader import load_protobuf_modules
from trigger_source import configure_trigger_source, read_trigger_source


pb, _pb_low = load_protobuf_modules(require_trigger_source=True)

def parse_channels(spec):
    channels = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            first_text, last_text = token.split("-", 1)
            first, last = int(first_text), int(last_text)
            if last < first:
                raise argparse.ArgumentTypeError(
                    f"descending channel range: {token}"
                )
            channels.extend(range(first, last + 1))
        else:
            channels.append(int(token))
    channels = list(dict.fromkeys(channels))
    if not channels or any(channel < 0 or channel > 39 for channel in channels):
        raise argparse.ArgumentTypeError("channels must be in 0..39")
    return channels


class V2Client:
    def __init__(self, endpoint, route, timeout_ms):
        self.route = route
        self.timeout_ms = timeout_ms
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt(
            zmq.IDENTITY,
            f"trigger-source-smoke-{os.getpid()}-{uuid.uuid4()}".encode(),
        )
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self.socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
        self.socket.connect(endpoint)

    def close(self):
        self.socket.close(0)
        self.context.term()

    @staticmethod
    def _ids():
        mask = (1 << 63) - 1
        now = time.time_ns()
        return (
            ((now << 16) ^ random.randrange(1 << 16)) & mask,
            ((now << 1) ^ random.randrange(1 << 16)) & mask,
        )

    def make_envelope(self, message_type, payload):
        envelope = pb.ControlEnvelopeV2()
        envelope.version = 2
        envelope.dir = pb.DIR_REQUEST
        envelope.type = message_type
        envelope.payload = payload
        envelope.task_id, envelope.msg_id = self._ids()
        envelope.timestamp_ns = time.time_ns()
        envelope.route = self.route
        return envelope

    def _receive(self, request):
        frames = [self.socket.recv()]
        while self.socket.getsockopt(zmq.RCVMORE):
            frames.append(self.socket.recv())
        reply = pb.ControlEnvelopeV2()
        if not reply.ParseFromString(frames[-1]):
            raise RuntimeError("server returned an invalid ControlEnvelopeV2")
        if reply.dir != pb.DIR_RESPONSE:
            raise RuntimeError(f"unexpected response direction {reply.dir}")
        if reply.correl_id != request.msg_id:
            raise RuntimeError(
                f"correlation mismatch: got {reply.correl_id}, "
                f"expected {request.msg_id}"
            )
        return reply

    def request(self, message_type, payload):
        request = self.make_envelope(message_type, payload)
        self.socket.send(request.SerializeToString())
        return self._receive(request)

    def request_payload(self, message_type, payload):
        reply = self.request(message_type, payload)
        return reply.type, reply.payload

    def stream(self, message_type, payload):
        request = self.make_envelope(message_type, payload)
        self.socket.send(request.SerializeToString())
        while True:
            yield self._receive(request)


def validate_dump_metadata(
    label,
    channel_list,
    samples,
    waveforms,
    data_count,
    timestamps,
):
    expected_data = len(channel_list) * samples * waveforms
    if data_count != expected_data:
        raise RuntimeError(
            f"{label}: data count {data_count}, expected {expected_data}"
        )
    if len(timestamps) != waveforms:
        raise RuntimeError(
            f"{label}: timestamp count {len(timestamps)}, expected {waveforms}"
        )
    if len(set(timestamps)) != len(timestamps):
        raise RuntimeError(f"{label}: duplicate timestamps detected")


def acquire_normal(client, source, channels, samples, waveforms):
    request = pb.DumpSpyBuffersRequest()
    request.channelList.extend(channels)
    request.numberOfSamples = samples
    request.numberOfWaveforms = waveforms
    request.softwareTrigger = source == "software"
    reply = client.request(
        pb.MT2_DUMP_SPYBUFFER_REQ,
        request.SerializeToString(),
    )
    if reply.type != pb.MT2_DUMP_SPYBUFFER_RESP:
        raise RuntimeError(f"normal: unexpected response type {reply.type}")
    response = pb.DumpSpyBuffersResponse()
    if not response.ParseFromString(reply.payload):
        raise RuntimeError("normal: invalid DumpSpyBuffersResponse")
    if not response.success:
        raise RuntimeError("normal: " + response.message)
    if list(response.channelList) != channels:
        raise RuntimeError("normal: response channel list mismatch")
    validate_dump_metadata(
        "normal",
        channels,
        samples,
        waveforms,
        len(response.data),
        list(response.timestamps),
    )
    return list(response.timestamps)


def acquire_chunked(client, source, channels, samples, waveforms, chunk_size):
    request = pb.DumpSpyBuffersChunkRequest()
    request.channelList.extend(channels)
    request.numberOfSamples = samples
    request.numberOfWaveforms = waveforms
    request.softwareTrigger = source == "software"
    request.requestID = str(uuid.uuid4())
    request.chunkSize = min(chunk_size, waveforms)

    data_count = 0
    timestamps = []
    waveform_count = 0
    expected_sequence = 0
    saw_final = False
    for reply in client.stream(
        pb.MT2_DUMP_SPYBUFFER_CHUNK_REQ,
        request.SerializeToString(),
    ):
        if reply.type != pb.MT2_DUMP_SPYBUFFER_CHUNK_RESP:
            raise RuntimeError(f"chunked: unexpected response type {reply.type}")
        response = pb.DumpSpyBuffersChunkResponse()
        if not response.ParseFromString(reply.payload):
            raise RuntimeError("chunked: invalid DumpSpyBuffersChunkResponse")
        if not response.success:
            raise RuntimeError("chunked: " + response.message)
        if response.requestID != request.requestID:
            raise RuntimeError("chunked: request ID mismatch")
        if response.chunkseq != expected_sequence:
            raise RuntimeError(
                f"chunked: sequence {response.chunkseq}, "
                f"expected {expected_sequence}"
            )
        if list(response.channelList) != channels:
            raise RuntimeError("chunked: response channel list mismatch")
        expected_sequence += 1
        data_count += len(response.data)
        timestamps.extend(response.timestamps)
        waveform_count += response.waveformCount
        if response.isFinal:
            saw_final = True
            break

    if not saw_final:
        raise RuntimeError("chunked: final response was not received")
    if waveform_count != waveforms:
        raise RuntimeError(
            f"chunked: waveform count {waveform_count}, expected {waveforms}"
        )
    validate_dump_metadata(
        "chunked",
        channels,
        samples,
        waveforms,
        data_count,
        timestamps,
    )
    return timestamps


def build_parser():
    parser = argparse.ArgumentParser(
        description="Smoke-test the DAPHNE spybuffer trigger-source selector."
    )
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9876)
    parser.add_argument("--route", default="mezz/0")
    parser.add_argument("--channels", type=parse_channels, default=parse_channels("0"))
    parser.add_argument("--samples", type=int, default=256)
    parser.add_argument("--waveforms", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=2)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument(
        "--selector-only",
        action="store_true",
        help="Exercise source write/readback without acquiring waveforms.",
    )
    parser.add_argument(
        "--hardware-source",
        choices=("external", "timing", "all"),
        default=None,
        help=(
            "Also acquire with this hardware source. The corresponding "
            "laboratory trigger must be present."
        ),
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not 1 <= args.samples <= 2048:
        parser.error("--samples must be in 1..2048")
    if args.waveforms < 1:
        parser.error("--waveforms must be positive")
    if not 1 <= args.chunk_size <= args.waveforms:
        parser.error("--chunk-size must be in 1..waveforms")
    if args.timeout_ms < 1:
        parser.error("--timeout-ms must be positive")

    endpoint = f"tcp://{args.ip}:{args.port}"
    print("DAPHNE spybuffer trigger-source smoke test")
    print(f"  endpoint          : {endpoint}")
    print(f"  route             : {args.route}")
    print(f"  channels          : {args.channels}")
    print(f"  samples/waveforms : {args.samples}/{args.waveforms}")

    client = V2Client(endpoint, args.route, args.timeout_ms)
    original_source = None
    failure = None
    try:
        original_source = read_trigger_source(pb, client.request_payload)
        print(f"[INFO] initial trigger source: {original_source}")

        for source in ("software", "external", "timing", "all"):
            configure_trigger_source(pb, client.request_payload, source)
            print(f"[PASS] selector write/readback: {source}")

        if not args.selector_only:
            configure_trigger_source(pb, client.request_payload, "software")
            normal_timestamps = acquire_normal(
                client,
                "software",
                args.channels,
                args.samples,
                args.waveforms,
            )
            print(
                f"[PASS] software normal acquisition: "
                f"{len(normal_timestamps)} fresh waveforms"
            )
            chunked_timestamps = acquire_chunked(
                client,
                "software",
                args.channels,
                args.samples,
                args.waveforms,
                args.chunk_size,
            )
            print(
                f"[PASS] software chunked acquisition: "
                f"{len(chunked_timestamps)} fresh waveforms"
            )

        if args.hardware_source:
            configure_trigger_source(
                pb,
                client.request_payload,
                args.hardware_source,
            )
            timestamps = acquire_normal(
                client,
                args.hardware_source,
                args.channels,
                args.samples,
                args.waveforms,
            )
            print(
                f"[PASS] {args.hardware_source} normal acquisition: "
                f"{len(timestamps)} fresh waveforms"
            )
    except Exception as exc:
        failure = exc
        print(f"[FAIL] {exc}")
    finally:
        if original_source is not None:
            try:
                configure_trigger_source(
                    pb,
                    client.request_payload,
                    original_source,
                )
                print(f"[RESTORE] trigger source: {original_source}")
            except Exception as exc:
                print(f"[FAIL] could not restore trigger source: {exc}")
                if failure is None:
                    failure = exc
        client.close()

    if failure is not None:
        return 1
    print("[PASS] trigger-source smoke test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
