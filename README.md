Introduction

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

Installation procedure and application execution

To start developing in a DAPHNE V3/Mezz, follow this procedure to compile the software:

-- to install ZeroMQ
wget https://github.com/zeromq/libzmq/releases/download/v4.3.4/zeromq-4.3.4.tar.gz
tar xvzf zeromq-4.3.4.tar.gz
cd zeromq-4.3.4
./configure --host=aarch64-linux-gnu
make -j4 
sudo make install

-- to install cppzmq (header only library)
git clone https://github.com/zeromq/cppzmq.git
cd cppzmq
mkdir build && cd build
cmake .. -DCPPZMQ_BUILD_TESTS=OFF 

-- to install abseil

mkdir ~/software/abseil-install
git clone https://github.com/abseil/abseil-cpp.git
cd abseil-cpp
mkdir build && cd build
cmake .. -DCMAKE_POSITION_INDEPENDENT_CODE=ON -DCMAKE_BUILD_TYPE=Release -DABSL_ENABLE_INSTALL=ON -DBUILD_TESTING=OFF -DCMAKE_INSTALL_PREFIX=~/software/abseil-install
make -j4
make install

-- to install protobuf

git clone --recursive https://github.com/protocolbuffers/protobuf.git
cd protobuf
git checkout v30.1
git submodule update --init --recursive
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -Dprotobuf_BUILD_SHARED_LIBS=ON -DCMAKE_INSTALL_PREFIX=/usr/local -Dprotobuf_BUILD_TESTS=OFF -Dprotobuf_BUILD_EXAMPLES=OFF -Dabsl_DIR=$HOME/software/abseil-install/lib64/cmake/absl
make -j4 
sudo make install

-- compile the Daphne Slow control application
-- first, clone the repository
cd ~/daphneZMQ
mkdir build && cd build 
cmake ..
make -j4 

-- Ejecutar app 
sudo ./DaphneSlowController -ip <IP-ADDRESS> -port <PORT>
-- example: sudo ./DaphneSlowController -ip 193.206.157.36 -port 9000

Examples
