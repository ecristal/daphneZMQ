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
parser.add_argument("-afe", type=int, required=True, choices=range(0, 5), help="AFE Block to set. Default 0.")
parser.add_argument("-vgain_value", type=int, required=True, help="Vgain Value to set. Default 0.")
parser.add_argument("-configure_all", action='store_true', help="Configure all AFE blocks with the same Vgain value.")
# Parse arguments
args = parser.parse_args()

context = zmq.Context()
socket = context.socket(zmq.DEALER)
socket.setsockopt(zmq.IDENTITY, b"client-compat")
ip_addr = "tcp://{}:{}".format(args.ip, args.port)
socket.connect(ip_addr)

if args.configure_all:
    afe_blocks = range(5)
else:
    afe_blocks = [args.afe]

for afe in afe_blocks:
    request = pb_low.cmd_writeAFEVGAIN()
    request.afeBlock = afe
    request.vgainValue = args.vgain_value
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

socket.close()