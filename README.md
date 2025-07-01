# Introduction

This project is the Slow Control software written in C++ to control and configure the DAPHNE V3/Mezz of the DUNE experiment. The project implements a ZMQ repply server that listen to incoming messages,
executes configuration commands or retrieves sampled waveforms form the spybuffers and replies to the client. 
The messaging protocol is implemented using Google's protobuf library. There are two levels of messaging commands: 
  - High level commands: These are commands used to configure multiple systems at a time or high level configuration. Examples:
      - Dump the spybuffers of a specific channel.
      - Configure the entire frontend.
      - Request voltage levels information. 
  - Low level commands: These are atomic configuration commands that operates on specific systems.
      - Configure CH offset.
      - Configure AFE5808A registers.
      - Configure AFE BIAS voltage.

These commands are defined in the following files:
  - srcs/protobuf/daphneV3_high_level_confs.proto
  - srcs/protobuf/daphneV3_low_level_confs.proto

# Installation procedure and application execution
## Installation

To start developing in a DAPHNE V3/Mezz, follow this procedure to install the required libraries:

First, clone, build and install the ZeroMQ library.
```sh
wget https://github.com/zeromq/libzmq/releases/download/v4.3.4/zeromq-4.3.4.tar.gz
tar xvzf zeromq-4.3.4.tar.gz
cd zeromq-4.3.4
./configure --host=aarch64-linux-gnu
make -j4 
sudo make install
```


Second, clone and install the header-only cppzmq library.
```sh
git clone https://github.com/zeromq/cppzmq.git
cd cppzmq
mkdir build && cd build
cmake .. -DCPPZMQ_BUILD_TESTS=OFF 
```

Third, clone, build and install the abseil library.
```sh
mkdir ~/software/abseil-install
git clone https://github.com/abseil/abseil-cpp.git
cd abseil-cpp
mkdir build && cd build
cmake .. -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_BUILD_TYPE=Release -DABSL_ENABLE_INSTALL=ON -DBUILD_TESTING=OFF -DCMAKE_INSTALL_PREFIX=~/software/abseil-install
make -j4
make install
```

Fourth, clone, build and install the protobuf library.
```sh
git clone --recursive https://github.com/protocolbuffers/protobuf.git
cd protobuf
git checkout v30.1
git submodule update --init --recursive
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -Dprotobuf_BUILD_SHARED_LIBS=ON -DCMAKE_INSTALL_PREFIX=/usr/local -Dprotobuf_BUILD_TESTS=OFF -Dprotobuf_BUILD_EXAMPLES=OFF -Dabsl_DIR=$HOME/software/abseil-install/lib64/cmake/absl
make -j4 
sudo make install
```

Fifth, and finally clone this repository, build the Slow Control Application
```sh
git clone https://github.com/ecristal/daphneZMQ.git
cd ~/daphneZMQ
mkdir build && cd build 
cmake ..
make -j4
``` 
## Execution
Execute the application.
```sh
sudo ./DaphneSlowController -ip <IP-ADDRESS> -port <PORT>
#example: sudo ./DaphneSlowController -ip 193.206.157.36 -port 9000
```
## Usage and examples
To be able to send commands, the user must develop a client software using C++ or Python. The python client is recommended for it's ease of develop. The protobuf library of the high and low level commands are available in the srcs/protobuf/ folder. 

The python protobuf package is requires and can be installed with the following command:
```sh
pip install protobuf
```

## Example 1: Configure the bias control and AFE Bias Voltage
In this example, this small client is executed in the ./client folder in the repository. The protobuf libraries are imported as `pb_high` and `pb_low`. The client configures:

  - Bias Control: The Bias Control value is the configurable maximum voltage output.
  - Bias Value:  The Bias voltage value of each AFE block.  

Two functions converts the BIAS control and bias voltage to the DAC units required for the configuration: 
  - `def biasVolts2DAC(volts)`
  - `def biasControlVolts2DAC(volts)`

For this specific example, the client configure the Bias Control value to 55.0V and the Bias Voltage value to 10.0, 20.0, 30.0, 40.0, 50.0 for AFE 0 to AFE 4, repectively.


``` python
import zmq
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from srcs.protobuf import daphneV3_high_level_confs_pb2 as pb_high
from srcs.protobuf import daphneV3_low_level_confs_pb2 as pb_low

def biasVolts2DAC(volts):
    dac_values = []
    for i in range(len(volts)):
        dac_values.append(int((26.1/(26.1+1000))*1000.0*volts[i]))
    return dac_values

def biasControlVolts2DAC(volts):
    return (1.0/74.0)*volts*1000.0

biasAFE_Volts = [10.0, 20.0, 30.0, 40.0, 50.0]
biasAFE_DAC = biasVolts2DAC(biasAFE_Volts)
biasControlVolts = 55.0
biasControlDAC = int(biasControlVolts2DAC(biasControlVolts))


request = pb_low.cmd_writeVbiasControl()
request.vBiasControlValue = biasControlDAC
request.enable = True
envelope = pb_high.ControlEnvelope()
envelope.type = pb_high.WRITE_VBIAS_CONTROL
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

if responseEnvelope.type == pb_high.WRITE_VBIAS_CONTROL:
    response = pb_low.cmd_writeVbiasControl_response()
    response.ParseFromString(responseEnvelope.payload)
    print("Success:", response.success)
    print("Message:", response.message)
socket.close()

for afe in range(5):
    request = pb_low.cmd_writeAFEBiasSet()
    request.afeBlock = afe
    request.biasValue = biasAFE_DAC[afe]
    envelope = pb_high.ControlEnvelope()
    envelope.type = pb_high.WRITE_AFE_BIAS_SET
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

    if responseEnvelope.type == pb_high.WRITE_AFE_BIAS_SET:
        response = pb_low.cmd_writeAFEBiasSet_response()
        response.ParseFromString(responseEnvelope.payload)
        print("Success:", response.success)
        print("Message:", response.message)
    socket.close()
```



