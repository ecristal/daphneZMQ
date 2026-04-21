#!/usr/bin/env python3
import zmq
import sys
import daphneV3_high_level_confs_pb2 as high_pb2

def main(ip="10.73.137.161", port=40001):
    context = zmq.Context()
    socket = context.socket(zmq.DEALER)
    socket.connect(f"tcp://{ip}:{port}")
    print(f"[CLIENT] Connected to tcp://{ip}:{port}")

    # Build ControlEnvelope
    req = high_pb2.ControlEnvelope()
    req.version = 2
    req.command = "get_endpoint_status"

    # Send request
    socket.send(req.SerializeToString())
    print("[CLIENT] Request sent, waiting for reply...")

    # Receive reply
    reply_bytes = socket.recv()
    reply = high_pb2.ControlEnvelope()
    reply.ParseFromString(reply_bytes)

    print("[CLIENT] Reply received:")
    print(f"  success = {reply.success}")
    print(f"  message = {reply.message}")

    if reply.HasField("endpoint_status"):
        print("  Endpoint state:", reply.endpoint_status.state)
        print("  PLL locked:", reply.endpoint_status.pll_locked)
        print("  Clock frequency:", reply.endpoint_status.clk_freq_hz)

if __name__ == "__main__":
    ip = sys.argv[1] if len(sys.argv) > 1 else "10.73.137.161"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 40001
    main(ip, port)
