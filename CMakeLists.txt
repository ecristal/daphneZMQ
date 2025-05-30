cmake_minimum_required(VERSION 3.10)

project(daphneZMQ LANGUAGES CXX)

add_library(GTest::gtest INTERFACE IMPORTED GLOBAL)
add_library(GTest::gmock INTERFACE IMPORTED GLOBAL)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Add Abseil and cppzmq to the prefix path
list(APPEND CMAKE_PREFIX_PATH "/usr/local" "$ENV{HOME}/software/abseil-install")

# Find packages
find_package(Protobuf REQUIRED)
find_package(cppzmq REQUIRED)
find_package(absl REQUIRED)

# Auto-generate protobuf files
set(PROTO_HIGH_LEVEL_FILE "${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf/daphneV3_high_level_confs.proto")
set(PROTO_LOW_LEVEL_FILE "${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf/daphneV3_low_level_confs.proto")
#protobuf_generate_cpp(PROTO_SRCS PROTO_HDRS ${PROTO_HIGH_LEVEL_FILE} ${PROTO_LOW_LEVEL_FILE})

set(PROTO_DIR "${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf")

foreach(PROTO_FILE ${PROTO_HIGH_LEVEL_FILE} ${PROTO_LOW_LEVEL_FILE})
    get_filename_component(PROTO_FILE_NAME ${PROTO_FILE} NAME_WE)
    set(pb_cc "${PROTO_DIR}/${PROTO_FILE_NAME}.pb.cc")
    set(pb_h "${PROTO_DIR}/${PROTO_FILE_NAME}.pb.h")
    set(pb_py "${PROTO_DIR}/${PROTO_FILE_NAME}.pb.py")

    add_custom_command(
        OUTPUT ${pb_cc} ${pb_h}
        COMMAND ${Protobuf_PROTOC_EXECUTABLE}
        ARGS --cpp_out=${PROTO_DIR} --proto_path=${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf ${PROTO_FILE}
        DEPENDS ${PROTO_FILE}
        COMMENT "Generating C++ protobuf files for ${PROTO_FILE_NAME}"
    )

    add_custom_command(
        OUTPUT ${pb_py}
        COMMAND ${Protobuf_PROTOC_EXECUTABLE}
        ARGS --python_out=${PROTO_DIR} --proto_path=${CMAKE_CURRENT_SOURCE_DIR}/srcs/protobuf ${PROTO_FILE}
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

# Source files
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

# Executables
add_executable(publisher srcs/publisher.cpp srcs/DevMem.cpp)
target_link_libraries(publisher PRIVATE cppzmq)

add_executable(subscriber srcs/subscriber.cpp srcs/DevMem.cpp)
target_link_libraries(subscriber PRIVATE cppzmq)

add_executable(srv srcs/srv.cpp ${SOURCES})
target_link_libraries(srv PRIVATE cppzmq)

add_executable(srv_reg srcs/srv_reg.cpp ${SOURCES})
target_link_libraries(srv_reg PRIVATE cppzmq)

add_executable(daphne_test
    srcs/daphne_test.cpp
    ${SOURCES}
    ${PROTO_SRCS}
    ${PROTO_HDRS}
)

add_executable(DaphneSlowController
    srcs/DaphneSlowController.cpp
    ${SOURCES}
    ${PROTO_SRCS}
    ${PROTO_HDRS}
)

target_link_libraries(daphne_test
    PRIVATE
    cppzmq
    protobuf::libprotobuf
    absl::base
    absl::log_severity
    absl::raw_logging_internal
    absl::log_internal_check_op
    absl::log_internal_message
)

target_link_libraries(DaphneSlowController
    PRIVATE
    cppzmq
    protobuf::libprotobuf
    absl::base
    absl::log_severity
    absl::raw_logging_internal
    absl::log_internal_check_op
    absl::log_internal_message
)

# Print useful info
message(STATUS "Protobuf version: ${Protobuf_VERSION}")
message(STATUS "Abseil include: ${absl_INCLUDE_DIRS}")
message(STATUS "Abseil libs: ${absl_LIBRARIES}")
