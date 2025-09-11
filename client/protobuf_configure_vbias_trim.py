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

def biasVolts2DAC(volts):
    dac_values = []
    for i in range(len(volts)):
        dac_values.append(int((26.1/(26.1+1000))*1000.0*volts[i]))
    return dac_values

def biasControlVolts2DAC(volts):
    return (1.0/74.0)*volts*1000.0

parser = argparse.ArgumentParser(description="Channel bias and Trim configuration.")
# Add also limiter range [0-39] to this line to -channel argument
parser.add_argument("-ip", type=str, required=True, help="IP address of DAPHNE.")
parser.add_argument("-port", type=int, required=False, default=9000, help="Port number of DAPHNE. Default 9000.")
parser.add_argument("-channel", type=int, choices=range(0, 40), required=True, help="Channel number (0-39).")
parser.add_argument("-bias", type=float, required=True, help="Bias voltage.")
parser.add_argument("-bias_control", type=float, required=True, help="Bias control voltage. Sets the maximum bias voltage.")
parser.add_argument("-trim", type=int, required=True, help="Channel trim voltage.")
parser.add_argument("-set_as_DAC", action='store_true', help="Enable this flag to set bias as DAC value.")

# Parse arguments
args = parser.parse_args()

channel = args.channel
afeNumber = channel // 8
biasAFE_Volts = [0.0, 0.0, 0.0, 0.0, 0.0]
biasAFE_Volts[afeNumber] = args.bias
biasControlVolts = args.bias_control
trimValue = args.trim

if not args.set_as_DAC:
    biasAFE_DAC = biasVolts2DAC(biasAFE_Volts)  
    biasControlDAC = int(biasControlVolts2DAC(biasControlVolts))

context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)

request = pb_low.cmd_writeVbiasControl()
request.vBiasControlValue = biasControlDAC
request.enable = True
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.WRITE_VBIAS_CONTROL
envelope.payload = request.SerializeToString()

response_bytes = send_envelope_and_get_reply(socket, envelope)
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.WRITE_VBIAS_CONTROL:
    response = pb_low.cmd_writeVbiasControl_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)

request = pb_low.cmd_writeAFEBiasSet()
request.afeBlock = afeNumber
request.biasValue = biasAFE_DAC[afeNumber]
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.WRITE_AFE_BIAS_SET
envelope.payload = request.SerializeToString()

response_bytes = send_envelope_and_get_reply(socket, envelope)
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.WRITE_AFE_BIAS_SET:
    response = pb_low.cmd_writeAFEBiasSet_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)

request = pb_low.cmd_writeTrim_singleChannel()
request.trimChannel = channel
request.trimValue = trimValue
request.trimGain = False
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.WRITE_TRIM_CH
envelope.payload = request.SerializeToString()

response_bytes = send_envelope_and_get_reply(socket, envelope)
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.WRITE_TRIM_CH:
    response = pb_low.cmd_writeTrim_singleChannel_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)

socket.close()