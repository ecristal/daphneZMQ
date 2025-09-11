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
parser.add_argument("-afeFunction", type=str, required=True, choices=list(available_afe_functions.keys()), help="AFE function to configure.")
parser.add_argument("-afeNumber", type=int, required=True, choices=range(0, 5), help="AFE number to configure.")
parser.add_argument("-value", type=int, required=True, help="AFE number to configure.")
# Parse arguments
args = parser.parse_args()
# Setup ZMQ context once
context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)

# parse the other arguments
afe_function = args.afeFunction
afe_number = args.afeNumber
value = args.value

#Let's validate the value according to the dictionary available_afe_functions
valid_range = available_afe_functions[afe_function]
# if the returned value is [0, 1] it means the possible values are True or False
# if the returned value is [0, 0xFF] it means the possible values are 0-255, for example
# if the returned value is a list or more than two elements, it means the possible values are only contained in the list

if len(valid_range) == 2:
    if valid_range[0] == 0 and valid_range[1] == 1:
        # Boolean value
        if value not in [0, 1]:
            raise ValueError(f"Invalid value for {afe_function}: {value}. Expected 0 or 1.")
    else:
        # Integer value between 0 and 255
        if value <= valid_range[0] and value >= valid_range[1]:
            raise ValueError(f"Invalid value for {afe_function}: {value}. Expected {valid_range[0]}-{valid_range[1]}.")
else:
    # List of valid values
    if value not in valid_range:
        raise ValueError(f"Invalid value for {afe_function}: {value}. Expected one of {valid_range}.")

request = pb_low.cmd_writeAFEFunction()
request.afeBlock = afe_number
request.function = afe_function
request.configValue = value
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

socket.close()