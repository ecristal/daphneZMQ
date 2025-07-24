#!/bin/bash
# This runs your binary as root under gdbserver using a Unix domain socket

# Start gdbserver with Unix domain socket
sudo /usr/local/gdb10/bin/gdbserver 127.0.0.1:1234 ./build/DaphneSlowController --ip 193.206.157.36 --port 9000
sleep 1