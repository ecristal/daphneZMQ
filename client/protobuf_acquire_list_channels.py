import zmq
import sys
import os
import time
import uuid
from typing import Optional, Dict
from tqdm import tqdm
import argparse
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

# ----------------------------- ZMQ helpers -----------------------------

def make_dealer(context: zmq.Context, endpoint: str, identity: Optional[bytes] = None) -> zmq.Socket:
    s = context.socket(zmq.DEALER)
    s.setsockopt(zmq.LINGER, 0)
    if identity is None:
        identity = f"client-{uuid.uuid4()}".encode()
    s.setsockopt(zmq.IDENTITY, identity)
    s.connect(endpoint)
    return s


def send_envelope_and_get_reply(socket: zmq.Socket, envelope: pb_high.ControlEnvelope) -> bytes:
    socket.send(envelope.SerializeToString())
    frames = [socket.recv()]
    while socket.getsockopt(zmq.RCVMORE):
        frames.append(socket.recv())
    return frames[-1]


def stream_envelope(socket: zmq.Socket, envelope: pb_high.ControlEnvelope):
    socket.send(envelope.SerializeToString())
    while True:
        frames = [socket.recv()]
        while socket.getsockopt(zmq.RCVMORE):
            frames.append(socket.recv())
        payload = frames[-1]
        env = pb_high.ControlEnvelope()
        env.ParseFromString(payload)
        yield env

# ---------------------------- HWM / credit -----------------------------

def compute_credit(numberOfSamples: int, chunkWaveform: int, nChannels: int,
                   bytes_per_sample: int = 4, budget_mb: int = 128,
                   min_credit: int = 32, max_credit: int = 4096) -> int:
    chunk_bytes = max(1, int(numberOfSamples) * int(chunkWaveform) * int(nChannels) * int(bytes_per_sample))
    credit = (int(budget_mb) * 1024 * 1024) // chunk_bytes
    return int(min(max(credit, min_credit), max_credit))

# ------------------------------- CLI ----------------------------------

parser = argparse.ArgumentParser(description="Acquire waveforms from multiple channels (legacy or streaming).")
parser.add_argument("-ip", type=str, required=True, help="IP address of DAPHNE.")
parser.add_argument("-port", type=int, default=9000, help="Server port.")
parser.add_argument("-foldername", type=str, required=True, help="Folder location to save channel data.")
parser.add_argument("-channel_list", type=int, nargs='+', choices=range(0, 40), required=True, help="List of channels (0-39). Example: 0 1 2 3")
parser.add_argument("-N", type=int, required=True, help="Number of waveforms.")
parser.add_argument("-L", type=int, required=True, help="Length of each waveform.")
parser.add_argument("-software_trigger", action='store_true', help="Enable software trigger.")
parser.add_argument("-append_data", action='store_true', help="Append to existing per-channel files.")
parser.add_argument("-debug", action='store_true', help="Debug printout.")
# Streaming options
parser.add_argument("-legacy", action='store_true', help="Use legacy (non-streaming) API.")
parser.add_argument("-chunk", type=int, default= 5, help="Waveforms per chunk (hint for server).")
parser.add_argument("-net_buffer_mb", type=int, default=128, help="Approx memory budget for in-flight chunks (MB) to compute RCVHWM.")
parser.add_argument("-compress", action='store_true', help="Enable compression.")
parser.add_argument("-compression_format", type=str, choices=['7z', 'tar'], default='tar', help="Compression type (7z or gz tarball).")
parser.add_argument("-compression_level", type=int, default=1, choices=range(1, 10), help="7z compression level (1-9). Default 1.")
args = parser.parse_args()

# ----------------------------- Setup ----------------------------------

context = zmq.Context()
endpoint = f"tcp://{args.ip}:{args.port}"
socket = make_dealer(context, endpoint, identity=b"client-compat")

n_channels = len(args.channel_list)

if not args.legacy:
    credit = compute_credit(args.L, min(args.chunk, args.N), n_channels, budget_mb=args.net_buffer_mb)
    socket.setsockopt(zmq.RCVHWM, credit)

if args.debug:
    print(f"Endpoint: {endpoint}")
    print(f"Channels: {args.channel_list} (n={n_channels}), N={args.N}, L={args.L}, SW_TRG={args.software_trigger}, STREAM={not args.legacy}, chunk={args.chunk}, RCVHWM={compute_credit(args.L, min(args.chunk, args.N), n_channels, budget_mb=args.net_buffer_mb) if not args.legacy else 'n/a'}")
    start_time = time.time()

mode = 'ab' if args.append_data else 'wb'
foldername = args.foldername

#Now, filename will be in a directory /foldername/channel_<channel>.dat
#make sure that the folder exists, if not, create it
if not os.path.exists(foldername):
    os.makedirs(foldername)

# -------------------------- Legacy path --------------------------------

if args.legacy:
    req = pb_high.DumpSpyBuffersRequest()
    req.channelList.extend(args.channel_list)
    req.numberOfWaveforms = args.N
    req.numberOfSamples = args.L
    req.softwareTrigger = bool(args.software_trigger)

    env = pb_high.ControlEnvelope()
    env.type = pb_high.DUMP_SPYBUFFER
    env.payload = req.SerializeToString()

    print(f"Requesting {args.N} waveforms (L={args.L}) on channels {args.channel_list}; SW_TRG={args.software_trigger}")
    resp_bytes = send_envelope_and_get_reply(socket, env)

    resp_env = pb_high.ControlEnvelope()
    resp_env.ParseFromString(resp_bytes)
    assert resp_env.type == pb_high.DUMP_SPYBUFFER, f"Unexpected response type: {resp_env.type}"

    resp = pb_high.DumpSpyBuffersResponse()
    resp.ParseFromString(resp_env.payload)

    data = np.asarray(resp.data, dtype=np.uint32)
    try:
        y = data.reshape((args.N, n_channels, args.L))
    except ValueError:
        raise RuntimeError(f"Data size {data.size} not compatible with (N={args.N}, C={n_channels}, L={args.L})")

    for idx, ch in enumerate(args.channel_list):
        fname = os.path.join(foldername, f"channel_{ch}.dat")
        if args.debug:
            print(f"Saving data for channel {ch} to {fname}")
        with open(fname, mode) as f:
            y[:, idx, :].astype(np.uint16, copy=False).tofile(f)

    if args.debug:
        dt = time.time() - start_time
        print(f"Done (legacy). Time: {dt//60:.0f}:{dt%60:.0f}")
    sys.exit(0)

# ------------------------- Streaming path ------------------------------

creq = pb_high.DumpSpyBuffersChunkRequest()
creq.channelList.extend(args.channel_list)
creq.numberOfWaveforms = args.N
creq.numberOfSamples = args.L
creq.softwareTrigger = bool(args.software_trigger)
creq.requestID = str(uuid.uuid4())
creq.chunkSize = max(1, min(args.chunk, args.N))

env = pb_high.ControlEnvelope()
env.type = pb_high.DUMP_SPYBUFFER_CHUNK
env.payload = creq.SerializeToString()

print(f"Streaming id={creq.requestID} N={args.N} L={args.L} chunk={creq.chunkSize} channels={args.channel_list} SW_TRG={args.software_trigger}")

# Open all files once
files: Dict[int, any] = {ch: open(os.path.join(foldername, f"channel_{ch}.dat"), mode) for ch in args.channel_list}
wf_written = 0
try:
    with tqdm(total=args.N, unit='wf') as pbar:
        for resp_env in stream_envelope(socket, env):
            if resp_env.type != pb_high.DUMP_SPYBUFFER_CHUNK:
                continue
            chunk = pb_high.DumpSpyBuffersChunkResponse()
            chunk.ParseFromString(resp_env.payload)
            if not chunk.success:
                print(f"Server error: {chunk.message}")
                break
            if chunk.data:
                # Expect layout: [wf0_ch0[0:L], wf0_ch1[0:L], ..., wfK_chC-1[0:L], wf1_ch0[0:L], ...]
                arr = np.asarray(chunk.data, dtype=np.uint32)
                wf_count = int(chunk.waveformCount)
                try:
                    y = arr.reshape((wf_count, n_channels, args.L))
                except ValueError:
                    raise RuntimeError(f"Chunk data size {arr.size} not compatible with (wf_count={wf_count}, C={n_channels}, L={args.L})")
                for idx, ch in enumerate(args.channel_list):
                    y[:, idx, :].astype(np.uint16, copy=False).tofile(files[ch])
                wf_written += wf_count
                pbar.update(wf_count)
            if chunk.isFinal:
                break
finally:
    for f in files.values():
        try:
            f.close()
        except Exception:
            pass

if args.debug:
    dt = time.time() - start_time
    print(f"Done (stream). Received {wf_written}/{args.N} waveforms. Time: {dt//60:.0f}:{dt%60:.0f}")

# add 7z or gzip compression
if args.compress:
    compression_type = args.compression_format
    if args.debug:
        print(f"Compressing data with {compression_type} ...")
        start_time = time.time()
    filenames = ''
    filename_list = []
    for ch in args.channel_list:
        filename = os.path.join(foldername, f"channel_{ch}.dat")
        filenames += f' {filename}'
        filename_list.append(filename)
        #delete .dat if if compression is succesful
        #Check if 7z is installed
    filename_c = os.path.join(foldername, "compressed_channels")
    if os.system(f'{compression_type} --help') != 0:
        print(f"{compression_type} is not installed. Please install it to use {compression_type} compression.")
        sys.exit(1)
    if compression_type == '7z':
        os.system(f'7z a -mx={args.compression_level} {filename_c}.7z {filenames} -y')
        if os.path.exists(f'{filename_c}.7z'):
            for filename in filename_list:
                os.remove(filename)
    elif compression_type == 'tar':
        os.system(f'tar -czvf {filename_c}.tar.gz {filenames}')
        if os.path.exists(f'{filename_c}.tar.gz'):
            for filename in filename_list:
                os.remove(filename)