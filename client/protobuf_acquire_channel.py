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

parser = argparse.ArgumentParser(description="Acquisition of waveforms.")
parser.add_argument("-ip", type=str, required=True, help="IP address of DAPHNE.")
parser.add_argument("-port", type=int, required=False, default=9000, help="Port number of DAPHNE.")
parser.add_argument("-channel", type=int, choices=range(0, 40), required=True, help="0-39")
parser.add_argument("-filename", type=str, required=True, help="File location")
parser.add_argument("-N", type=int, required=True, help="Number of waveform")
parser.add_argument("-L", type=int, required=True, help="Length of waveform")
parser.add_argument("-software_trigger", action='store_true', help="Enables software trigger.")

# Parse arguments
args = parser.parse_args()

# Setup ZMQ context once
context = zmq.Context()

# Create the figure and line once
fig, ax = plt.subplots()
y = np.zeros(args.L)

socket = context.socket(zmq.REQ)
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)
channel = args.channel
filename = args.filename
number_of_waveforms = args.N
length_of_waveforms = args.L
software_trigger = args.software_trigger

data_file = open(filename, 'ab') 

for i in tqdm(range(number_of_waveforms), total = number_of_waveforms):
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

    y = np.array(response.data, dtype='uint16')
    y.astype('uint16').tofile(data_file)
data_file.close()

