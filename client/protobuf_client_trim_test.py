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
parser.add_argument("-ip", type=str, default="127.0.0.1", help="IP address of DAPHNE (default 127.0.0.1).")
parser.add_argument("-port", type=int, required=False, default=9876, help="Port number of DAPHNE. Default 9876.")
# Parse arguments
args = parser.parse_args()

context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)

for trimCH in range(40):
    request = pb_low.cmd_writeTrim_singleChannel()
    request.trimChannel = trimCH
    request.trimValue = 0#(trimCH + 1)*100
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
