import zmq

# Define the IP address and port of the server
address = "tcp://193.206.157.36:9000"

# Create a ZeroMQ context
context = zmq.Context()

# Create a request socket
requester = context.socket(zmq.REQ)

# Set a 10-second timeout for receiving responses
requester.setsockopt(zmq.RCVTIMEO, 10000)  # Timeout in milliseconds

# Connect to the server
requester.connect(address)

print("Connected to server at {}. Type your message and press Enter to send.".format(address))
print("Note: The script will timeout if no response is received within 10 seconds.")

while True:
    # Read input from the keyboard
    message = input("Enter message: ")
    
    if message.lower() == "exit":
        print("Exiting...")
        break
    
    try:
        # Send the message to the server
        requester.send_string(message)
        print(f"Sent message: {message}")

        # Wait for the response from the server
        response = requester.recv_string()
        print(f"Received response: {response}")
    except zmq.error.Again:
        print("No response received within 10 seconds. Retrying...")

# Close the socket and terminate the context when done
requester.close()
context.term()
