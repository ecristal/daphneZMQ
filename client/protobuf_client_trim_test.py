import zmq
import json
import time
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

for trimCH in range(40):
    request = pb_low.cmd_writeTrim_singleChannel()
    request.trimChannel = trimCH
    request.trimValue = 0#(trimCH + 1)*100
    request.trimGain = False
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_TRIM_CH
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

    if responseEnvelope.type == pb_high.WRITE_TRIM_CH:
        response = pb_low.cmd_writeTrim_singleChannel_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()