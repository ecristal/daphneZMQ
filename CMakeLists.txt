cmake_minimum_required(VERSION 3.10)
project(daphneZMQ LANGUAGES CXX)

# ---------------- Basics ----------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# ---------------- OpenMP (optional) -----
find_package(OpenMP QUIET)
if(OpenMP_CXX_FOUND)
  message(STATUS "OpenMP found")
else()
  message(STATUS "OpenMP not found; continuing without it")
endif()

# ---------------- Protobuf --------------
find_package(Protobuf REQUIRED)
message(STATUS "Using protoc: ${Protobuf_PROTOC_EXECUTABLE}")
include_directories(${Protobuf_INCLUDE_DIRS})

set(PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf)
set(PROTO_FILES
  ${PROTO_DIR}/daphneV3_high_level_confs.proto
  ${PROTO_DIR}/daphneV3_low_level_confs.proto
)

# Generate into build tree, mirroring source paths, so headers are at:
#   ${CMAKE_CURRENT_BINARY_DIR}/srcs/protobuf/*.pb.h
protobuf_generate_cpp(PROTO_SRCS PROTO_HDRS ${PROTO_FILES})

add_library(daphne_proto ${PROTO_SRCS} ${PROTO_HDRS})
target_include_directories(daphne_proto PUBLIC
  ${CMAKE_CURRENT_BINARY_DIR}
  ${PROTO_DIR}
)
target_link_libraries(daphne_proto PUBLIC protobuf::libprotobuf)

# ---------------- cppzmq / libzmq -------
find_package(cppzmq CONFIG QUIET)
if(cppzmq_FOUND)
  message(STATUS "cppzmq package found")
else()
  message(STATUS "cppzmq package not found; using header-only fallback")
  find_path(CPPZMQ_INCLUDE_DIR NAMES zmq.hpp
            HINTS /usr/include /usr/local/include $ENV{HOME}/.local/include)
  if(NOT CPPZMQ_INCLUDE_DIR)
    message(FATAL_ERROR "zmq.hpp not found; set CPPZMQ_INCLUDE_DIR or install cppzmq headers")
  endif()
  add_library(cppzmq INTERFACE)
  target_include_directories(cppzmq INTERFACE ${CPPZMQ_INCLUDE_DIR})
endif()

find_library(ZMQ_LIB NAMES zmq HINTS /usr/lib /usr/local/lib)
if(NOT ZMQ_LIB)
  message(FATAL_ERROR "libzmq not found; install zeromq (libzmq)")
endif()

# ---------------- CLI11 (fallback) ------
find_package(CLI11 CONFIG QUIET)
if(CLI11_FOUND)
  message(STATUS "CLI11 package found")
else()
  message(STATUS "CLI11 package not found; using header-only fallback")
  find_path(CLI11_INCLUDE_DIR NAMES CLI/CLI.hpp
            HINTS /usr/include /usr/local/include $ENV{HOME}/.local/include)
  if(NOT CLI11_INCLUDE_DIR)
    message(FATAL_ERROR "CLI/CLI.hpp not found; set CLI11_INCLUDE_DIR or install CLI11 headers")
  endif()
  add_library(CLI11::CLI11 INTERFACE IMPORTED)
  set_target_properties(CLI11::CLI11 PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES "${CLI11_INCLUDE_DIR}")
endif()

# ---------------- Threads / i2c ----------
find_package(Threads REQUIRED)
find_library(I2C_LIB NAMES i2c HINTS /usr/lib /usr/local/lib)
if(NOT I2C_LIB)
  message(STATUS "libi2c not found; continuing without it (only needed if you call i2c API)")
endif()

# ---------------- Sources ----------------
set(SOURCES
  srcs/DevMem.cpp
  srcs/FpgaRegDict.cpp
  srcs/reg.cpp
  srcs/FpgaReg.cpp
  srcs/Spi.cpp
  srcs/SpyBuffer.cpp
  srcs/I2CDevice.cpp
  srcs/DaphneI2CDrivers.cpp
  srcs/SpiDevice.cpp
  srcs/DaphneSpiDrivers.cpp
  srcs/Afe.cpp
  srcs/FrontEnd.cpp
  srcs/Endpoint.cpp
  srcs/Dac.cpp
  srcs/Daphne.cpp
  srcs/DaphneSlowController.cpp
)

add_executable(DaphneSlowController ${SOURCES})
target_include_directories(DaphneSlowController PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_BINARY_DIR}
  ${PROTO_DIR}
)
target_link_libraries(DaphneSlowController PRIVATE
  daphne_proto
  cppzmq
  ${ZMQ_LIB}
  protobuf::libprotobuf
  CLI11::CLI11
  Threads::Threads
)
if(OpenMP_CXX_FOUND)
  target_link_libraries(DaphneSlowController PRIVATE OpenMP::OpenMP_CXX)
endif()
if(I2C_LIB)
  target_link_libraries(DaphneSlowController PRIVATE ${I2C_LIB})
endif()

# ---------------- Diagnostics ------------
message(STATUS "ZMQ lib: ${ZMQ_LIB}")
message(STATUS "cppzmq target: " $<TARGET_EXISTS:cppzmq>)
message(STATUS "CLI11 target: " $<TARGET_EXISTS:CLI11::CLI11>)
message(STATUS "I2C lib: ${I2C_LIB}")
