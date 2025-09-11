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
parser.add_argument("-channel", type=int, required=True, choices=range(40), help="Offset Channel to set. Default 0.")
parser.add_argument("-offset_value", type=int, required=True, help="Offset Value to set. Default 0.")
parser.add_argument("-configure_all", action='store_true', help="Configure all Offset channels with the same Offset value.")
# Parse arguments
args = parser.parse_args()

context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)

if args.configure_all:
    channels = range(40)
else:
    channels = [args.channel]

for channel in channels:
    request = pb_low.cmd_writeOFFSET_singleChannel()
    request.offsetChannel = channel
    request.offsetValue = args.offset_value
    request.offsetGain = False
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_OFFSET_CH
    envelope.payload = request.SerializeToString()

    response_bytes = send_envelope_and_get_reply(socket, envelope)
    responseEnvelope = pb_high.ControlEnvelope()
    responseEnvelope.ParseFromString(response_bytes)

    if responseEnvelope.type == pb_high.WRITE_OFFSET_CH:
        response = pb_low.cmd_writeOFFSET_singleChannel_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
socket.close()