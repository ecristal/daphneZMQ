import zmq
import json
import time
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

def biasVolts2DAC(volts):
    dac_values = []
    for i in range(len(volts)):
        dac_values.append(int((26.1/(26.1+1000))*1000.0*volts[i]))
    return dac_values

def biasControlVolts2DAC(volts):
    return (1.0/74.0)*volts*1000.0

biasAFE_Volts = [0.0, 0.0, 0.0, 0.0, 31.5]
biasAFE_DAC = biasVolts2DAC(biasAFE_Volts)
biasControlVolts = 55.0
biasControlDAC = int(biasControlVolts2DAC(biasControlVolts))


request = pb_low.cmd_writeVbiasControl()
request.vBiasControlValue = biasControlDAC
request.enable = True
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.WRITE_VBIAS_CONTROL
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

if responseEnvelope.type == pb_high.WRITE_VBIAS_CONTROL:
    response = pb_low.cmd_writeVbiasControl_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()

for afe in range(5):
    request = pb_low.cmd_writeAFEBiasSet()
    request.afeBlock = afe
    request.biasValue = biasAFE_DAC[afe]
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_BIAS_SET
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

    if responseEnvelope.type == pb_high.WRITE_AFE_BIAS_SET:
        response = pb_low.cmd_writeAFEBiasSet_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()