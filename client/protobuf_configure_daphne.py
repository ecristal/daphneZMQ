import zmq
import json
import time
import sys
import os
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low
from client_dictionaries import *

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
parser.add_argument("-vgain", type=int, required=False, default=1600, help="VGain value for AFE blocks. Default 1600.")
parser.add_argument("-ch_offset", type=int, required=False, default=2275, help="Pedestal offset for channels. Default 2275.")
parser.add_argument("-align_afes", action='store_true', help="Enables alignment of AFE blocks.")
parser.add_argument("-enable_integrators", action='store_true', help="Enables AFE5808A integrators.")
parser.add_argument("-lpf_cutoff", type=int, choices=[10, 15, 20, 30], default=10, help="LPF cutoff frequency in MHz. Default 10Mhz.")
parser.add_argument("-pga_clamp_level", type=str, choices=["-2 dBFS", "0 dBFS", "-2 dBFS_lowpower", "0 dBFS_lowpower"], default="0 dBFS", help="PGA clamp level. Default 0 dBFS.")
parser.add_argument("-pga_gain_control", type=str, choices=["24 dB", "30 dB"], default="24 dB", help="PGA gain control. Default 24 dB.")
parser.add_argument("-lna_gain_control", type=str, choices=["18 dB", "24 dB", "12 dB"], default="12 dB", help="LNA gain control. Default 12 dB.")
parser.add_argument("-lna_input_clamp", type=str, choices=["auto", "1.5 Vpp", "1.15 Vpp", "0.6 Vpp"], default="auto", help="LNA input clamp. Default auto.")


# Parse arguments
args = parser.parse_args()
# Setup ZMQ context once
context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)

# parse the other arguments
vgain_value = args.vgain
ch_offset_value = args.ch_offset
align_afes = args.align_afes
enable_integrators = args.enable_integrators
lpf_cutoff = lpf_dict[args.lpf_cutoff]   
pga_clamp_level = pga_clamp_level_dict[args.pga_clamp_level]
pga_gain_control = pga_gain_control_dict[args.pga_gain_control]
lna_gain_control = lna_gain_control_dict[args.lna_gain_control]
lna_input_clamp = lna_input_clamp_dict[args.lna_input_clamp]

for offsetCH in range(40):
    request = pb_low.cmd_writeOFFSET_singleChannel()
    request.offsetChannel = offsetCH
    request.offsetValue = ch_offset_value
    request.offsetGain = False
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_OFFSET_CH
    envelope.payload = request.SerializeToString()

    # Send via ZMQ
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_OFFSET_CH:
        response = pb_low.cmd_writeOFFSET_singleChannel_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    

for afe in range(5):
    request = pb_low.cmd_writeAFEVGAIN()
    request.afeBlock = afe
    request.vgainValue = vgain_value
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_VGAIN
    envelope.payload = request.SerializeToString()

    
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_VGAIN:
        response = pb_low.cmd_writeAFEVgain_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    
request = pb_low.cmd_doAFEReset()
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.DO_AFE_RESET
envelope.payload = request.SerializeToString()

response_bytes = send_envelope_and_get_reply(socket, envelope)
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.DO_AFE_RESET:
    response = pb_low.cmd_doAFEReset_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)

#---------------------------------------

request = pb_low.cmd_setAFEPowerState()
request.powerState = False
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.SET_AFE_POWERSTATE
envelope.payload = request.SerializeToString()

response_bytes = send_envelope_and_get_reply(socket, envelope)
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.SET_AFE_POWERSTATE:
    response = pb_low.cmd_setAFEPowerState_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)


for afe in range(5):

    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'SERIALIZED_DATA_RATE'
    request.configValue = 1
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)

    #---------------------------------------

    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'ADC_OUTPUT_FORMAT'
    request.configValue = 1
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)

    #---------------------------------------

    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'LPF_PROGRAMMABILITY'
    request.configValue = lpf_cutoff
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'PGA_INTEGRATOR_DISABLE'
    request.configValue = not enable_integrators
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'PGA_CLAMP_LEVEL'
    request.configValue = pga_clamp_level
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'ACTIVE_TERMINATION_ENABLE'
    request.configValue = 0
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'LNA_INPUT_CLAMP_SETTING'
    request.configValue = lna_input_clamp
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'LNA_INTEGRATOR_DISABLE'
    request.configValue = not enable_integrators
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    
    #---------------------------------------
    #---------------------------------------
    request = pb_low.cmd_writeAFEFunction()
    request.afeBlock = afe
    request.function = 'LNA_GAIN'
    request.configValue = lna_gain_control
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_FUNCTION
    envelope.payload = request.SerializeToString()

    
    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_AFE_FUNCTION:
        response = pb_low.cmd_writeAFEFunction_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    
request = pb_low.cmd_setAFEPowerState()
request.powerState = True
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.SET_AFE_POWERSTATE
envelope.payload = request.SerializeToString()

response_bytes = send_envelope_and_get_reply(socket, envelope)
responseEnvelope = pb_high.ControlEnvelope()
responseEnvelope.ParseFromString(response_bytes)

if responseEnvelope.type == pb_high.SET_AFE_POWERSTATE:
    response = pb_low.cmd_setAFEPowerState_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)

if align_afes:
    request = pb_low.cmd_alignAFEs()
    #request.afe = afe
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.ALIGN_AFE
    envelope.payload = request.SerializeToString()


    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.ALIGN_AFE:
        response = pb_low.cmd_alignAFEs_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)


socket.close()