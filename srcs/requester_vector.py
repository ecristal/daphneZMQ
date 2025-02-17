import zmq
import struct
import argparse
import numpy as np

parser = argparse.ArgumentParser(description="Vector data requester.")
# Define command-line arguments
parser.add_argument("-ip", type=str, required=True, help="IP address")
parser.add_argument("-port", type=int, required=True, help="Port number (1-65535)")

# Parse arguments
args = parser.parse_args()

# Server connection details
address = "tcp://" + args.ip + ":" + str(args.port)

# Create a ZMQ context
context = zmq.Context()
requester = context.socket(zmq.REQ)
requester.connect(address)

# Get user input for the number of vectors
num_vectors = int(input("Enter number of vectors to request: "))

# Send read command
command = f"read {num_vectors}"
requester.send_string(command)
print(f"Sent: {command}")

# Receive data
for i in range(num_vectors):
    try:
        # Receive raw binary data
        raw_data = requester.recv()  
        vector = np.frombuffer(raw_data, dtype=np.float64)  # Convert to numpy array

        if len(vector) != 2048:
            print(f"⚠️ Warning: Received vector {i+1}/{num_vectors} has {len(vector)} values instead of 2048.")

        print(f"✅ Received vector {i+1}/{num_vectors} ({len(vector)} values)")
    except zmq.error.ZMQError as e:
        print(f"❌ Error receiving vector {i+1}: {e}")
        break  # Stop if an error occurs

# Cleanup
requester.close()
context.term()
