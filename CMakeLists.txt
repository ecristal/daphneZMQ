cmake_minimum_required(VERSION 3.10)
project(daphneZMQ LANGUAGES CXX)

# -------- Basics ----------------------------------------------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Prefer release unless the user says otherwise
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# Optional: OpenMP if available (quiet on Petalinux if not)
find_package(OpenMP QUIET)
if(OpenMP_CXX_FOUND)
  message(STATUS "OpenMP found")
else()
  message(STATUS "OpenMP not found; continuing without it")
endif()

# -------- Options / Overrides --------------------------------------
# You can pass these at configure time, e.g.
#   -DCPPZMQ_INCLUDE_DIR=/usr/local/include
#   -DCLI11_INCLUDE_DIR=/home/petalinux/.local/include
option(ENABLE_ABSL "Link against Abseil if available" OFF)

# -------- Protobuf (required) --------------------------------------
find_package(Protobuf REQUIRED)
message(STATUS "Protobuf version: ${Protobuf_VERSION}")
if(NOT Protobuf_PROTOC_EXECUTABLE)
  message(FATAL_ERROR "protoc not found; set -DProtobuf_PROTOC_EXECUTABLE=/path/to/protoc")
endif()

# -------- cppzmq (header-only) + libzmq -----------------------------
# Try CMake package first, then fall back to headers + lib search
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

# -------- CLI11 (header-only) --------------------------------------
find_package(CLI11 CONFIG QUIET)
if(CLI11_FOUND)
  message(STATUS "CLI11 package found")
else()
  message(STATUS "CLI11 package not found; using header-only fallback")
  # Allow override via -DCLI11_INCLUDE_DIR=...
  if(NOT CLI11_INCLUDE_DIR)
    # Try common locations
    find_path(CLI11_INCLUDE_DIR NAMES CLI/CLI.hpp
              HINTS /usr/include /usr/local/include $ENV{HOME}/.local/include)
  endif()
  if(NOT CLI11_INCLUDE_DIR)
    message(FATAL_ERROR "CLI/CLI.hpp not found; set CLI11_INCLUDE_DIR or install CLI11 headers")
  endif()
  add_library(CLI11::CLI11 INTERFACE IMPORTED)
  set_target_properties(CLI11::CLI11 PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES "${CLI11_INCLUDE_DIR}")
endif()

# -------- Abseil (optional) ----------------------------------------
set(ABSL_LINK_LIBS "")
if(ENABLE_ABSL)
  find_package(absl QUIET)
  if(absl_FOUND)
    message(STATUS "Abseil found; linking base + log_severity")
    list(APPEND ABSL_LINK_LIBS absl::base absl::log_severity)
  else()
    message(STATUS "Abseil not found; continuing without it")
  endif()
endif()

# -------- Threads / libc / i2c -------------------------------------
find_package(Threads REQUIRED)
find_library(I2C_LIB NAMES i2c HINTS /usr/lib /usr/local/lib)
if(NOT I2C_LIB)
  message(STATUS "libi2c not found; continuing without it (only needed if you call i2c API)")
endif()

# -------- Protobuf codegen (C++ only; Python not needed here) -------
set(PROTO_DIR            ${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf)
set(PROTO_HIGH_LEVEL     ${PROTO_DIR}/daphneV3_high_level_confs.proto)
set(PROTO_LOW_LEVEL      ${PROTO_DIR}/daphneV3_low_level_confs.proto)

foreach(PROTO_FILE ${PROTO_HIGH_LEVEL} ${PROTO_LOW_LEVEL})
  get_filename_component(_name ${PROTO_FILE} NAME_WE)
  set(_cc ${PROTO_DIR}/${_name}.pb.cc)
  set(_hh ${PROTO_DIR}/${_name}.pb.h)

  add_custom_command(
    OUTPUT ${_cc} ${_hh}
    COMMAND ${Protobuf_PROTOC_EXECUTABLE}
    ARGS --cpp_out=${PROTO_DIR} --proto_path=${PROTO_DIR} ${PROTO_FILE}
    DEPENDS ${PROTO_FILE}
    COMMENT "Generating C++ protobuf for ${_name}"
    VERBATIM
  )

  list(APPEND PROTO_SRCS ${_cc})
  list(APPEND PROTO_HDRS ${_hh})
endforeach()

add_library(daphne_proto STATIC ${PROTO_SRCS} ${PROTO_HDRS})
target_include_directories(daphne_proto PUBLIC ${PROTO_DIR})
target_link_libraries(daphne_proto PUBLIC protobuf::libprotobuf)

# -------- Project sources ------------------------------------------
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
target_include_directories(DaphneSlowController
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${PROTO_DIR}
)

# Link line kept simple and robust for Petalinux
target_link_libraries(DaphneSlowController
  PRIVATE
    daphne_proto
    cppzmq
    ${ZMQ_LIB}
    protobuf::libprotobuf
    CLI11::CLI11
    Threads::Threads
)

# Optional libs
if(OpenMP_CXX_FOUND)
  target_link_libraries(DaphneSlowController PRIVATE OpenMP::OpenMP_CXX)
endif()
if(I2C_LIB)
  target_link_libraries(DaphneSlowController PRIVATE ${I2C_LIB})
endif()
if(ABSL_LINK_LIBS)
  target_link_libraries(DaphneSlowController PRIVATE ${ABSL_LINK_LIBS})
endif()

# -------- Nice diagnostics -----------------------------------------
message(STATUS "ZMQ lib: ${ZMQ_LIB}")
message(STATUS "cppzmq target: " $<TARGET_EXISTS:cppzmq>)
message(STATUS "CLI11 target: " $<TARGET_EXISTS:CLI11::CLI11>)
message(STATUS "I2C lib: ${I2C_LIB}")
