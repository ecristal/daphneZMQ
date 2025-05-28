#!/bin/bash
# This runs your binary as root under gdbserver using a Unix domain socket

# Start gdbserver with Unix domain socket
sudo /usr/local/gdb10/bin/gdbserver 127.0.0.1:1234 ./build/DaphneSlowController
sleep 1