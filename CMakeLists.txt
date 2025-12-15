cmake_minimum_required(VERSION 3.10)

# Some macOS CommandLineTools installs require an explicit sysroot for libc++ headers.
if(APPLE AND (NOT CMAKE_OSX_SYSROOT OR CMAKE_OSX_SYSROOT STREQUAL ""))
  execute_process(
    COMMAND xcrun --show-sdk-path
    OUTPUT_VARIABLE _SDKROOT
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  if(_SDKROOT)
    set(CMAKE_OSX_SYSROOT "${_SDKROOT}" CACHE PATH "macOS SDK root" FORCE)
  endif()
endif()

if(APPLE AND EXISTS "${CMAKE_OSX_SYSROOT}/usr/include/c++/v1")
  add_compile_options(-isystem "${CMAKE_OSX_SYSROOT}/usr/include/c++/v1")
endif()

project(daphne_server LANGUAGES CXX)

# ---------------- Basics ----------------
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

option(DAPHNE_BUILD_PY_PROTO "Generate python *_pb2.py into build tree" ON)
option(DAPHNE_BUNDLE_ZEROMQ "Build bundled libzmq from third_party" OFF)
set(DAPHNE_DEPS_TARBALL_DIR "" CACHE PATH "Directory containing the pinned dependency tarball (see deps/deps.lock.cmake)")

if(DAPHNE_DEPS_TARBALL_DIR AND NOT DAPHNE_DEPS_TARBALL_DIR STREQUAL "")
  include("${CMAKE_CURRENT_SOURCE_DIR}/cmake/daphne_deps.cmake")
  daphne_use_locked_deps(TARBALL_DIR "${DAPHNE_DEPS_TARBALL_DIR}")
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
  ${CMAKE_CURRENT_BINARY_DIR}/srcs
  ${PROTO_DIR}
)
target_link_libraries(daphne_proto PUBLIC protobuf::libprotobuf)

if(DAPHNE_BUILD_PY_PROTO)
  # Also regenerate Python stubs in the build tree so clients can import the
  # same schema the C++ binary was built against.
  set(PY_PROTO_OUT ${CMAKE_CURRENT_BINARY_DIR}/srcs/protobuf)
  file(MAKE_DIRECTORY ${PY_PROTO_OUT})
  add_custom_command(
    OUTPUT
      ${PY_PROTO_OUT}/daphneV3_high_level_confs_pb2.py
      ${PY_PROTO_OUT}/daphneV3_low_level_confs_pb2.py
    COMMAND ${Protobuf_PROTOC_EXECUTABLE}
      --python_out=${PY_PROTO_OUT}
      -I ${PROTO_DIR}
      ${PROTO_DIR}/daphneV3_high_level_confs.proto
      ${PROTO_DIR}/daphneV3_low_level_confs.proto
    DEPENDS ${PROTO_FILES}
    COMMENT "Generating Python protobuf stubs"
  )
  add_custom_target(daphne_proto_py ALL DEPENDS
    ${PY_PROTO_OUT}/daphneV3_high_level_confs_pb2.py
    ${PY_PROTO_OUT}/daphneV3_low_level_confs_pb2.py
  )
endif()

# ---------------- cppzmq / libzmq -------
find_package(cppzmq CONFIG QUIET)
if(cppzmq_FOUND)
  message(STATUS "cppzmq package found")
else()
  message(STATUS "cppzmq package not found; using header-only fallback")
  find_path(CPPZMQ_INCLUDE_DIR NAMES zmq.hpp
            HINTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/cppzmq
                  /usr/include /usr/local/include /opt/homebrew/include /opt/local/include
                  $ENV{HOME}/.local/include)
  if(NOT CPPZMQ_INCLUDE_DIR)
    message(FATAL_ERROR "zmq.hpp not found; set CPPZMQ_INCLUDE_DIR or install cppzmq headers")
  endif()
  add_library(cppzmq INTERFACE)
  target_include_directories(cppzmq INTERFACE ${CPPZMQ_INCLUDE_DIR})
endif()

set(DAPHNE_ZMQ_TARGET "")
if(DAPHNE_BUNDLE_ZEROMQ)
  if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/third_party/zeromq-4.3.4/CMakeLists.txt")
    message(FATAL_ERROR "DAPHNE_BUNDLE_ZEROMQ=ON but third_party/zeromq-4.3.4 is missing")
  endif()

  # Keep the bundled build as small and dependency-free as possible.
  set(BUILD_SHARED OFF CACHE BOOL "" FORCE)
  set(BUILD_STATIC ON CACHE BOOL "" FORCE)
  set(BUILD_TESTS OFF CACHE BOOL "" FORCE)
  set(WITH_DOC OFF CACHE BOOL "" FORCE)
  set(WITH_DOCS OFF CACHE BOOL "" FORCE)
  set(ENABLE_CURVE OFF CACHE BOOL "" FORCE)
  set(WITH_LIBSODIUM OFF CACHE BOOL "" FORCE)
  set(WITH_TLS OFF CACHE BOOL "" FORCE)

  add_subdirectory(third_party/zeromq-4.3.4 EXCLUDE_FROM_ALL)
  set(DAPHNE_ZMQ_TARGET libzmq-static)
else()
  find_library(ZMQ_LIB NAMES zmq HINTS /usr/lib /usr/local/lib /lib)
  if(NOT ZMQ_LIB)
    message(FATAL_ERROR "libzmq not found; set DAPHNE_BUNDLE_ZEROMQ=ON or install zeromq (libzmq)")
  endif()
  add_library(daphne_zmq_lib INTERFACE)
  target_link_libraries(daphne_zmq_lib INTERFACE ${ZMQ_LIB})
  set(DAPHNE_ZMQ_TARGET daphne_zmq_lib)
endif()

# ---------------- CLI11 (fallback) ------
find_package(CLI11 CONFIG QUIET)
if(CLI11_FOUND)
  message(STATUS "CLI11 package found")
else()
  message(STATUS "CLI11 package not found; using header-only fallback")
  find_path(CLI11_INCLUDE_DIR NAMES CLI/CLI.hpp
            HINTS ${CMAKE_CURRENT_SOURCE_DIR}/third_party/CLI11/include
                  /usr/include /usr/local/include /opt/homebrew/include /opt/local/include
                  $ENV{HOME}/.local/include
                  /home/petalinux/zmq/CLI11 /home/petalinux/zmq/CLI11/include)
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
  srcs/server_controller/handlers.cpp
  srcs/server_controller/monitoring.cpp
  srcs/server_controller/spybuffer_chunker.cpp
  srcs/server_controller/router_server.cpp
  srcs/server_controller/main.cpp
)

add_executable(daphneServer ${SOURCES})
target_include_directories(daphneServer PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
  ${CMAKE_CURRENT_SOURCE_DIR}/srcs
  ${CMAKE_CURRENT_BINARY_DIR}
  ${CMAKE_CURRENT_BINARY_DIR}/srcs
  ${CMAKE_CURRENT_BINARY_DIR}/srcs/protobuf
  ${PROTO_DIR}
)
target_link_libraries(daphneServer PRIVATE
  daphne_proto
  cppzmq
  ${DAPHNE_ZMQ_TARGET}
  CLI11::CLI11
  Threads::Threads
)
if(OpenMP_CXX_FOUND)
  target_link_libraries(daphneServer PRIVATE OpenMP::OpenMP_CXX)
endif()
if(I2C_LIB)
  target_link_libraries(daphneServer PRIVATE ${I2C_LIB})
endif()

add_executable(daphne_zmq_server
  srcs/srv.cpp
  srcs/DevMem.cpp
)
target_link_libraries(daphne_zmq_server PRIVATE
  cppzmq
  ${DAPHNE_ZMQ_TARGET}
)
if(OpenMP_CXX_FOUND)
  target_link_libraries(daphne_zmq_server PRIVATE OpenMP::OpenMP_CXX)
endif()

# ---------------- Diagnostics ------------
message(STATUS "ZMQ lib: ${ZMQ_LIB}")
message(STATUS "ZMQ target: ${DAPHNE_ZMQ_TARGET} (bundled=${DAPHNE_BUNDLE_ZEROMQ})")
message(STATUS "cppzmq target: " $<TARGET_EXISTS:cppzmq>)
message(STATUS "CLI11 target: " $<TARGET_EXISTS:CLI11::CLI11>)
message(STATUS "I2C lib: ${I2C_LIB}")
