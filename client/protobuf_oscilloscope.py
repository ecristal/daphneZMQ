import zmq
import sys
import os
import time
import argparse

import matplotlib.pyplot as plt
import numpy as np

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

parser = argparse.ArgumentParser(description="Oscilloscope.")
parser.add_argument("-channel", type=int, required=True, help="0-39.")
parser.add_argument("-L", type=int, required=True, help="Length of waveform.")
parser.add_argument("-software_trigger", type=bool, required=False, help="Enables software trigger.")

# Parse arguments
args = parser.parse_args()
# Setup ZMQ context once
context = zmq.Context()

# Create the figure and line once
fig, ax = plt.subplots()
x = np.arange(2048)
y = np.zeros_like(x)
line, = ax.plot(x, y)
ax.set_ylim(5000, 10000)  # Adjust to your expected signal range

plt.ion()  # Turn on interactive mode
plt.show()
socket = context.socket(zmq.REQ)
socket.connect("tcp://193.206.157.36:9000")
channel = args.channel
length_of_waveforms = args.L
software_trigger = args.software_trigger

while True:
    # DO SOFTWARE TRIGGER
    if(software_trigger):
        request = pb_low.cmd_doSoftwareTrigger()
        envelope = pb_high.ControlEnvelope()
        envelope.type = pb_high.DO_SOFTWARE_TRIGGER
        envelope.payload = request.SerializeToString()

        socket.send(envelope.SerializeToString())
        response_bytes = socket.recv()

        responseEnvelope = pb_high.ControlEnvelope()
        responseEnvelope.ParseFromString(response_bytes)

        if responseEnvelope.type == pb_high.DO_SOFTWARE_TRIGGER:
            response = pb_low.cmd_doSoftwareTrigger_response()
            response.ParseFromString(responseEnvelope.payload)
        # print("Success:", response.success)
        # print("Message:", response.message)

    # DUMP SPYBUFFER
    request = pb_high.DumpSpyBuffersRequest()
    request.channel = channel
    request.numberOfSamples = length_of_waveforms

    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.DUMP_SPYBUFFER
    envelope.payload = request.SerializeToString()

    socket.send(envelope.SerializeToString())
    response_bytes = socket.recv()

    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.DUMP_SPYBUFFER:
        response = pb_high.DumpSpyBuffersResponse()
        response.ParseFromString(responseEnvelope.payload)
        # print("Success:", response.success)
        # print("Message:", response.message)

    y = np.array(response.data)
    
    line.set_ydata(y)

    # Optionally adjust y-limits dynamically:
    # ax.set_ylim(y.min(), y.max())

    fig.canvas.draw()
    fig.canvas.flush_events()

    time.sleep(0.001)  # Slow down update rate if needed

