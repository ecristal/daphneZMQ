cmake_minimum_required(VERSION 3.10)

project(daphneZMQ LANGUAGES CXX)

add_compile_options(-fopenmp)
add_link_options(-fopenmp)


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
find_package(Threads REQUIRED)
find_package(CLI11 CONFIG REQUIRED)

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
# add_executable(publisher srcs/publisher.cpp srcs/DevMem.cpp)
# target_link_libraries(publisher PRIVATE cppzmq)

# add_executable(subscriber srcs/subscriber.cpp srcs/DevMem.cpp)
# target_link_libraries(subscriber PRIVATE cppzmq)

# add_executable(srv srcs/srv.cpp ${SOURCES})
# target_link_libraries(srv PRIVATE cppzmq)

# add_executable(srv_reg srcs/srv_reg.cpp ${SOURCES})
# target_link_libraries(srv_reg PRIVATE cppzmq)

# add_executable(daphne_test
#     srcs/daphne_test.cpp
#     ${SOURCES}
#     ${PROTO_SRCS}
#     ${PROTO_HDRS}
# )
# target_link_libraries(daphne_test
#     PRIVATE
#     cppzmq
#     protobuf::libprotobuf
#     absl::base
#     absl::log_severity
#     absl::raw_logging_internal
#     absl::log_internal_check_op
#     absl::log_internal_message
# )

add_executable(DaphneSlowController
    srcs/DaphneSlowController.cpp
    ${SOURCES}
    ${PROTO_SRCS}
    ${PROTO_HDRS}
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
    Threads::Threads
    -lc
)

# Print useful info
message(STATUS "Protobuf version: ${Protobuf_VERSION}")
message(STATUS "Abseil include: ${absl_INCLUDE_DIRS}")
message(STATUS "Abseil libs: ${absl_LIBRARIES}")

# Deployment and installation 

set(APP_NAME "DaphneSlowController")
set(APP_EXEC "${APP_NAME}")
set(APP_VERSION "V0_01_27")
set(APP_ICON "daphe_slow_controller_logo")
set(APP_COMMENT "Slow Control Interface for DAPHNE V3")
set(APPDIR "${CMAKE_BINARY_DIR}/${APP_NAME}_${APP_VERSION}")

configure_file(${CMAKE_CURRENT_SOURCE_DIR}/DaphneSlowController.desktop.in
               ${CMAKE_CURRENT_BINARY_DIR}/DaphneSlowController.desktop @ONLY)

# Install your executable
install(TARGETS ${APP_NAME}
        RUNTIME DESTINATION bin)

# Install dependencies (if needed explicitly)
# install(FILES <other_files> DESTINATION <destination>)

# --- Deployment Target using linuxdeploy ---
find_program(LINUXDEPLOY_EXECUTABLE linuxdeploy REQUIRED)

add_custom_target(deploy
    COMMAND ${CMAKE_COMMAND} -E remove_directory ${APPDIR}
    COMMAND ${LINUXDEPLOY_EXECUTABLE}
            --appdir=${APPDIR}
            --executable=$<TARGET_FILE:${APP_NAME}>
            --desktop-file=${CMAKE_CURRENT_BINARY_DIR}/${APP_NAME}.desktop
            --icon-file=${CMAKE_CURRENT_SOURCE_DIR}/icons/daphe_slow_controller_logo.png
            #--output appimage # too much lib requirements
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
    COMMENT "Deploying application ${APP_NAME} ${APP_VERSION}"
    VERBATIM)

# Ensure desktop file is generated before deployment
add_dependencies(deploy ${APP_NAME})

add_custom_target(package_tarball
    COMMAND ${CMAKE_COMMAND} -E tar "cfvz"
            ${CMAKE_BINARY_DIR}/${APP_NAME}_${APP_VERSION}.tar.gz
            ${APPDIR}
    DEPENDS deploy
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
    COMMENT "Compressing AppDir to tarball ${APP_NAME}_${APP_VERSION}.tar.gz"
)
