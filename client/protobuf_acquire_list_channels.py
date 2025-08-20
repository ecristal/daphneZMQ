import zmq
import sys
import os
import time
from tqdm import tqdm
import argparse


import matplotlib.pyplot as plt
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

def send_envelope_and_get_reply(socket, envelope) -> bytes:
    """
    Sends a protobuf ControlEnvelope and returns the last frame of the reply.
    Compatible with REP and ROUTER servers.
    """
    socket.send(envelope.SerializeToString())

    frames = [socket.recv()]
    while socket.getsockopt(zmq.RCVMORE):
        frames.append(socket.recv())

    return frames[-1]  # Payload is always in the last frame

parser = argparse.ArgumentParser(description="Acquisition of waveforms.")
parser.add_argument("-ip", type=str, required=True, help="IP address of DAPHNE.")
parser.add_argument("-port", type=int, required=False, default=9000, help="Port number of DAPHNE.")
parser.add_argument("-channel_list", type=int, nargs='+', choices=range(0, 40), required=True, help="List of channels (0-39). Example: 0 1 2 3")
parser.add_argument("-N", type=int, required=True, help="Number of waveform")
parser.add_argument("-L", type=int, required=True, help="Length of waveform")
parser.add_argument("-software_trigger", action='store_true', help="Enables software trigger.")
parser.add_argument("-append_data", action='store_true', help="Enables appending data to an existing file.")
parser.add_argument("-debug", action='store_true', required=False, help="Enables debug printout.")

# Parse arguments
args = parser.parse_args()

# Setup ZMQ context once
context = zmq.Context()

# Create the figure and line once
fig, ax = plt.subplots()
y = np.zeros(args.L)

socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)
channel_list = args.channel_list
number_of_waveforms = args.N
length_of_waveforms = args.L
software_trigger = args.software_trigger

if args.debug:
    print(f"IP: {args.ip}, Port: {args.port}, Channel: {channel_list}, N: {number_of_waveforms}, L: {length_of_waveforms}, Software Trigger: {software_trigger}")
    # Print execution time
    start_time = time.time()

#for i in tqdm(range(number_of_waveforms), total = number_of_waveforms):
# DO SOFTWARE TRIGGER
# if(software_trigger):
#     request = pb_low.cmd_doSoftwareTrigger()
#     envelope = pb_high.ControlEnvelope()
#     envelope.type = pb_high.DO_SOFTWARE_TRIGGER
#     envelope.payload = request.SerializeToString()

#     socket.send(envelope.SerializeToString())
#     response_bytes = socket.recv()

#     responseEnvelope = pb_high.ControlEnvelope()
#     responseEnvelope.ParseFromString(response_bytes)

#     if responseEnvelope.type == pb_high.DO_SOFTWARE_TRIGGER:
#         response = pb_low.cmd_doSoftwareTrigger_response()
#         response.ParseFromString(responseEnvelope.payload)
    # print("Success:", response.success)
    # print("Message:", response.message)

# DUMP SPYBUFFER
request = pb_high.DumpSpyBuffersRequest()
request.channelList.extend(channel_list)
request.numberOfWaveforms = args.N
if software_trigger:
    request.softwareTrigger = True
else:
    request.softwareTrigger = False
request.numberOfSamples = length_of_waveforms

envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.DUMP_SPYBUFFER
envelope.payload = request.SerializeToString()


print(f"Request sent to DAPHNE to acquire {args.N} waveforms of length {length_of_waveforms} on channels {channel_list}. Software trigger: {software_trigger}")
print("Waiting for response...")

response_bytes = send_envelope_and_get_reply(socket, envelope)

# print how much it took to receive the response in minutes:seconds
if args.debug:
    print("Response received from DAPHNE.")
    print(f"Time taken: {(time.time() - start_time) // 60:.0f}:{(time.time() - start_time) % 60:.0f}")

responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.DUMP_SPYBUFFER:
    response = pb_high.DumpSpyBuffersResponse()
    response.ParseFromString(responseEnvelope.payload)
    # print("Success:", response.success)
    # print("Message:", response.message)

y = np.array(response.data, dtype='uint32')
# y contains data from all channels in the order it was requested
# [channel1_wave0[0:L], channel2_wave0[0:L], ..., channel39_wave0[0:L] .... channel0_waveN[0:L], channel1_waveN[0:L], ..., channel39_waveN[0:L]]
# Reshape y to have channel1_wave0[0:L], channel1_wave1[0:L] ...
y = y.reshape((number_of_waveforms, len(channel_list), length_of_waveforms))
mode = 'ab' if args.append_data else 'wb'
for i, channel in enumerate(channel_list):
    filename = f"channel_{channel}.dat"
    if args.debug:
        print(f"Saving data for channel {channel} to {filename}")
    # Save each channel's waveforms to a separate file
    with open(filename, mode) as data_file:
        # To get each channel as a flat vector of all its samples across all waveforms:
        y[:, i, :].astype('uint16').tofile(data_file)

