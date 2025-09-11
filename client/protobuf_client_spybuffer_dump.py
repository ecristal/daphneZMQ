import zmq
import json
import time
import sys
import os
import argparse

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

parser = argparse.ArgumentParser(description="DAPHNE Configuration.")
parser.add_argument("-ip", type=str, required=True, help="IP address of DAPHNE.")
parser.add_argument("-port", type=int, required=False, default=9000, help="Port number of DAPHNE. Default 9000.")
# Parse arguments
args = parser.parse_args()

context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)

for offsetCH in range(40):
    request = pb_low.cmd_writeOFFSET_singleChannel()
    request.offsetChannel = offsetCH
    request.offsetValue = 2275
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

for afe in range(5):
    request = pb_low.cmd_writeAFEVGAIN()
    request.afeBlock = afe
    request.vgainValue = 1600#500*(afe+1)
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

request = pb_low.cmd_doAFEReset()
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.DO_AFE_RESET
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

if responseEnvelope.type == pb_high.DO_AFE_RESET:
    response = pb_low.cmd_doAFEReset_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()


request = pb_low.cmd_setAFEPowerState()
request.powerState = False
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.SET_AFE_POWERSTATE
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

if responseEnvelope.type == pb_high.SET_AFE_POWERSTATE:
    response = pb_low.cmd_setAFEPowerState_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()

for afe in range(5):
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'SERIALIZED_DATA_RATE'
    request.configValue = 1
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()

    #---------------------------------------

    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'ADC_OUTPUT_FORMAT'
    request.configValue = 1
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()

    #---------------------------------------

    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'LPF_PROGRAMMABILITY'
    request.configValue = 4
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'PGA_INTEGRATOR_DISABLE'
    request.configValue = 1
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'PGA_CLAMP_LEVEL'
    request.configValue = 2
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'ACTIVE_TERMINATION_ENABLE'
    request.configValue = 0
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'LNA_INPUT_CLAMP_SETTING'
    request.configValue = 2
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'LNA_INTEGRATOR_DISABLE'
    request.configValue = 1
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'LNA_GAIN'
    request.configValue = 2
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
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

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()

request = pb_low.cmd_setAFEPowerState()
request.powerState = True
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.SET_AFE_POWERSTATE
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

if responseEnvelope.type == pb_high.SET_AFE_POWERSTATE:
    response = pb_low.cmd_setAFEPowerState_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()


request = pb_low.cmd_alignAFEs()
#request.afe = afe
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
    response = pb_low.cmd_alignAFEs_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()

request = pb_low.cmd_doSoftwareTrigger()
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.DO_SOFTWARE_TRIGGER
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

if responseEnvelope.type == pb_high.DO_SOFTWARE_TRIGGER:
    response = pb_low.cmd_doSoftwareTrigger_response()
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