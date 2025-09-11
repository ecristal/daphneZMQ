import zmq
import sys
import os
import time
import uuid
from tqdm import tqdm
from typing import Optional
import argparse
import numpy as np
import matplotlib.pyplot as plt

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

# ------------------------------------------------------------------
# ZMQ helpers (compatible with REP and ROUTER servers)
# ------------------------------------------------------------------

def make_dealer(context: zmq.Context, endpoint: str, identity: Optional[bytes] = None) -> zmq.Socket:
    s = context.socket(zmq.DEALER)
    s.setsockopt(zmq.LINGER, 0)
    if identity is None:
        identity = f"client-{uuid.uuid4()}".encode()
    s.setsockopt(zmq.IDENTITY, identity)
    s.connect(endpoint)
    return s


def send_envelope_and_get_reply(sock: zmq.Socket, env: pb_high.ControlEnvelope) -> bytes:
    sock.send(env.SerializeToString())
    frames = [sock.recv()]
    while sock.getsockopt(zmq.RCVMORE):
        frames.append(sock.recv())
    return frames[-1]


def stream_envelope(sock: zmq.Socket, env: pb_high.ControlEnvelope):
    """Send once, then yield ControlEnvelope replies until server stops.
    Used for streaming chunk responses.
    """
    sock.send(env.SerializeToString())
    while True:
        frames = [sock.recv()]
        while sock.getsockopt(zmq.RCVMORE):
            frames.append(sock.recv())
        payload = frames[-1]
        resp_env = pb_high.ControlEnvelope()
        resp_env.ParseFromString(payload)
        yield resp_env
        # NOTE: caller decides when to break based on message content


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Acquisition of waveforms (legacy or streaming).")
parser.add_argument("-ip", type=str, required=True, help="IP address of DAPHNE.")
parser.add_argument("-port", type=int, default=9000, help="Server port.")
parser.add_argument("-channel", type=int, choices=range(0, 40), required=True, help="0-39")
parser.add_argument("-foldername", type=str, required=True, help="Folder location to save channel data.")
parser.add_argument("-N", type=int, required=True, help="Number of waveforms")
parser.add_argument("-L", type=int, required=True, help="Length of waveform")
parser.add_argument("-software_trigger", action='store_true', help="Enable software trigger")
parser.add_argument("-append_data", action='store_true', help="Append to existing file")
parser.add_argument("-debug", action='store_true', help="Debug printout")
parser.add_argument("-compress", action='store_true', help="Enable compression.")
parser.add_argument("-compression_format", type=str, choices=['7z', 'tar'], default='tar', help="Compression type (7z or gz tarball).")
parser.add_argument("-compression_level", type=int, default=1, choices=range(1, 10), help="7z compression level (1-9). Default 1.")
# Streaming options
parser.add_argument("-legacy", action='store_true', help="Use legacy (non-streaming) API")
parser.add_argument("-chunk", type=int, default=10, help="Waveforms per chunk (hint)")
args = parser.parse_args()

# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------
context = zmq.Context()

# Plot scaffolding (kept for parity; not required for streaming write-to-disk)
fig, ax = plt.subplots()
y = np.zeros(args.L, dtype=np.uint32)

endpoint = f"tcp://{args.ip}:{args.port}"
socket = make_dealer(context, endpoint, identity=b"client-compat")

channel = args.channel
foldername = args.foldername
N = args.N
L = args.L
software_trigger = args.software_trigger

#Now, filename will be in a directory /foldername/channel_<channel>.dat
#make sure that the folder exists, if not, create it
if not os.path.exists(foldername):
    os.makedirs(foldername)
filename = os.path.join(os.path.dirname(foldername), f"channel_{channel}.dat")

if args.debug:
    print(f"Endpoint: {endpoint}")
    print(f"IP: {args.ip}, Port: {args.port}, Channel: {channel}, Filename: {filename}, N: {N}, L: {L}, SW_TRG: {software_trigger}, STREAM: {not args.legacy}")
    start_time = time.time()

# ------------------------------------------------------------------
# Legacy single-shot mode
# ------------------------------------------------------------------
if args.legacy:
    req = pb_high.DumpSpyBuffersRequest()
    req.channelList.append(channel)
    req.numberOfWaveforms = N
    req.softwareTrigger = bool(software_trigger)
    req.numberOfSamples = L

    env = pb_high.ControlEnvelope()
    env.type = pb_high.DUMP_SPYBUFFER
    env.payload = req.SerializeToString()

    print(f"Requesting {N} waveforms (L={L}) on ch{channel}; SW_TRG={software_trigger}")
    resp_bytes = send_envelope_and_get_reply(socket, env)

    resp_env = pb_high.ControlEnvelope()
    resp_env.ParseFromString(resp_bytes)
    assert resp_env.type == pb_high.DUMP_SPYBUFFER, "Unexpected response type"

    resp = pb_high.DumpSpyBuffersResponse()
    resp.ParseFromString(resp_env.payload)

    data_u16 = np.asarray(resp.data, dtype=np.uint32).astype(np.uint16, copy=False)
    mode = 'ab' if args.append_data else 'wb'
    with open(filename, mode) as f:
        data_u16.tofile(f)

    if args.debug:
        dt = time.time() - start_time
        print(f"Done (legacy). Time: {dt//60:.0f}:{dt%60:.0f}")
    sys.exit(0)

# ------------------------------------------------------------------
# Streaming (chunked) mode
# ------------------------------------------------------------------
# Build request
creq = pb_high.DumpSpyBuffersChunkRequest()
creq.channelList.append(channel)
creq.numberOfWaveforms = N
creq.softwareTrigger = bool(software_trigger)
creq.numberOfSamples = L
creq.requestID = str(uuid.uuid4())
creq.chunkSize = max(1, min(args.chunk, N))

env = pb_high.ControlEnvelope()
env.type = pb_high.DUMP_SPYBUFFER_CHUNK
env.payload = creq.SerializeToString()

print(f"Streaming request id={creq.requestID} N={N} L={L} chunk={creq.chunkSize} ch={channel} SW_TRG={software_trigger}")

# Open file once and append chunks as they arrive
mode = 'ab' if args.append_data else 'wb'
wf_written = 0
with open(filename, mode) as f, tqdm(total=N, unit='wf') as pbar:
    for resp_env in stream_envelope(socket, env):
        if resp_env.type != pb_high.DUMP_SPYBUFFER_CHUNK:
            # ignore unrelated messages/types (or raise)
            continue
        chunk = pb_high.DumpSpyBuffersChunkResponse()
        chunk.ParseFromString(resp_env.payload)
        if not chunk.success:
            print(f"Server reported error: {chunk.message}")
            break
        # Write data chunk immediately as uint16
        if chunk.data:
            np.asarray(chunk.data, dtype=np.uint32).astype(np.uint16, copy=False).tofile(f)
        wf_written += chunk.waveformCount
        pbar.update(chunk.waveformCount)
        if chunk.isFinal:
            break

if args.debug:
    dt = time.time() - start_time
    print(f"Done (stream). Received {wf_written}/{N} waveforms. Time: {dt//60:.0f}:{dt%60:.0f}")

# add 7z compression
compression_format = args.compression_format

if args.compress:
    if args.debug:
        start_time = time.time()
    #remove .dat extension if present
    if filename.endswith('.dat'):
        filename_c = filename[:-4]
    #delete .dat if if compression is succesful
    #Check if 7z is installed
    # if os.system(f'{compression_format} --help') != 0:
    #     print(f"{compression_format} is not installed. Please install it to use {compression_format} compression.")
    #     sys.exit(1)
    if compression_format == '7z':
        os.system(f'7z a -mx={args.compression_level} {filename_c}.7z {filename} -y')
        if os.path.exists(f'{filename_c}.7z'):
            os.remove(filename)
    elif compression_format == 'tar':
        os.system(f'tar -czvf {filename_c}.tar.gz {filename}')
        if os.path.exists(f'{filename_c}.tar.gz'):
            os.remove(filename)
    if args.debug:
        dt = time.time() - start_time
        print(f"Done. Time: {dt//60:.0f}:{dt%60:.0f}")
