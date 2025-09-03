cmake_minimum_required(VERSION 3.10)
project(daphneZMQ LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)


# Add Abseil and cppzmq to the prefix path
list(APPEND CMAKE_PREFIX_PATH "/usr/local" "$ENV{HOME}/software/abseil-install")

# Find packages
find_package(Protobuf REQUIRED)
find_package(cppzmq REQUIRED)
find_package(absl REQUIRED)
find_package(Threads REQUIRED)

# Auto-generate protobuf files
set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf")
set(PROTO_FILES
    ${PROTO_DIR}/daphneV3_high_level_confs.proto
    ${PROTO_DIR}/daphneV3_low_level_confs.proto
)

foreach(PROTO_FILE ${PROTO_FILES})
    get_filename_component(PROTO_FILE_NAME ${PROTO_FILE} NAME_WE)
    set(pb_cc "${PROTO_DIR}/${PROTO_FILE_NAME}.pb.cc")
    set(pb_h "${PROTO_DIR}/${PROTO_FILE_NAME}.pb.h")
    set(pb_py "${PROTO_DIR}/${PROTO_FILE_NAME}.pb.py")

    add_custom_command(
        OUTPUT ${pb_cc} ${pb_h}
        COMMAND ${Protobuf_PROTOC_EXECUTABLE}
        ARGS --cpp_out=${PROTO_DIR} --proto_path=${PROTO_DIR} ${PROTO_FILE}
        DEPENDS ${PROTO_FILE}
        COMMENT "Generating C++ protobuf files for ${PROTO_FILE_NAME}"
    )

    add_custom_command(
        OUTPUT ${pb_py}
        COMMAND ${Protobuf_PROTOC_EXECUTABLE}
        ARGS --python_out=${PROTO_DIR} --proto_path=${PROTO_DIR} ${PROTO_FILE}
        DEPENDS ${PROTO_FILE}
        COMMENT "Generating Python protobuf files for ${PROTO_FILE_NAME}"
    )

    list(APPEND PROTO_SRCS ${pb_cc})
    list(APPEND PROTO_HDRS ${pb_h})
    list(APPEND PROTO_PY_SRCS ${pb_py})
endforeach()

add_custom_target(protobuf_py ALL DEPENDS ${PROTO_PY_SRCS})

include_directories(
    include
    ${PROTOBUF_INCLUDE_DIRS}
    ${cppzmq_INCLUDE_DIRS}
    ${absl_INCLUDE_DIRS}
)

# Core source files for DaphneSlowController
set(SOURCES
    srcs/DevMem.cpp
    srcs/FpgaRegDict.cpp
    srcs/reg.cpp
    srcs/FpgaReg.cpp
    srcs/Spi.cpp
    srcs/SpyBuffer.cpp
    srcs/Afe.cpp
    srcs/FrontEnd.cpp
    srcs/Endpoint.cpp
    srcs/Dac.cpp
    srcs/Daphne.cpp
)

# Executable
add_executable(DaphneSlowController
    srcs/DaphneSlowController.cpp
    ${SOURCES}
    ${PROTO_SRCS}
    ${PROTO_HDRS}
)

# Link everything, including Abseil logging libs
target_link_libraries(DaphneSlowController
    PRIVATE
    cppzmq
    protobuf::libprotobuf
    absl::base
    absl::log_severity
    absl::raw_logging_internal
    absl::log_internal_check_op
    absl::log_internal_message
    absl::log_internal_conditions
    absl::log_internal_format
    absl::log_internal_globals
    absl::log_internal_log_sink_set
    absl::log_internal_proto
    absl::log_internal_structured_proto
    absl::log_internal_fnmatch
    absl::strings
    absl::str_format_internal
    absl::symbolize
    absl::demangle_internal
    absl::time
    absl::throw_delegate
    absl::spinlock_wait
    Threads::Threads
)

# Install your executable
install(TARGETS DaphneSlowController
        RUNTIME DESTINATION bin)

# Print useful info
message(STATUS "Protobuf version: ${Protobuf_VERSION}")
message(STATUS "Abseil include: ${absl_INCLUDE_DIRS}")
message(STATUS "Abseil libs: ${absl_LIBRARIES}")
