import zmq

# Define the IP address and port to connect to
address = "tcp://193.206.157.36:9000"

# Create a ZeroMQ context
context = zmq.Context()

# Create a subscriber socket
subscriber = context.socket(zmq.SUB)

# Connect to the publisher
subscriber.connect(address)

# Subscribe to all messages (use "" for all, or use a specific topic)
subscriber.setsockopt_string(zmq.SUBSCRIBE, "")

print("Subscriber connected to {}. Waiting for messages...".format(address))

# Receive messages
while True:
    message = subscriber.recv_string()
    print("Received message:", message)
