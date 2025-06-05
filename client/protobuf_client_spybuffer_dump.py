import zmq
import json
import time
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

for offsetCH in range(40):
    request = pb_low.cmd_writeOFFSET_singleChannel()
    request.offsetChannel = offsetCH
    request.offsetValue = 2250
    request.offsetGain = False
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_OFFSET_CH
    envelope.payload = request.SerializeToString()

    # Send via ZMQ
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.connect("tcp://193.206.157.36:9000")
    socket.send(envelope.SerializeToString())

    # Receive response
    response_bytes = socket.recv()
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_OFFSET_CH:
        response = pb_low.cmd_writeOFFSET_singleChannel_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()

for afe in range(1):
    request = pb_low.cmd_writeAFEVGAIN()
    request.afeBlock = afe
    request.vgainValue = 1990#500*(afe+1)
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_VGAIN
    envelope.payload = request.SerializeToString()

    # Send via ZMQ
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.connect("tcp://193.206.157.36:9000")
    socket.send(envelope.SerializeToString())

    # Receive response
    response_bytes = socket.recv()
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_VGAIN:
        response = pb_low.cmd_writeAFEVgain_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()

request = pb_low.cmd_alignAFE()
request.afe = 0
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.ALIGN_AFE
envelope.payload = request.SerializeToString()

# Send via ZMQ
context = zmq.Context()
socket = context.socket(zmq.REQ)
socket.connect("tcp://193.206.157.36:9000")
socket.send(envelope.SerializeToString())

# Receive response
response_bytes = socket.recv()
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.ALIGN_AFE:
    response = pb_low.cmd_alignAFE_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()

request = pb_high.DumpSpyBuffersRequest()
request.channel = 0
request.numberOfSamples = 2048#500*(afe+1)
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.DUMP_SPYBUFFER
envelope.payload = request.SerializeToString()

# Send via ZMQ
context = zmq.Context()
socket = context.socket(zmq.REQ)
socket.connect("tcp://193.206.157.36:9000")
socket.send(envelope.SerializeToString())

# Receive response
response_bytes = socket.recv()
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.DUMP_SPYBUFFER:
    response = pb_high.DumpSpyBuffersResponse()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()

import matplotlib.pyplot as pl
import numpy as np
x = np.array(range(2048))
y = list(response.data)
pl.plot(x,np.array(y))
pl.show()