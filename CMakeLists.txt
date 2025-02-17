cmake_minimum_required(VERSION 3.10)

# Project information
project(daphneZMQ LANGUAGES CXX)

# Set C++ standard
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Add the path to cppzmqConfig.cmake if necessary
list(APPEND CMAKE_PREFIX_PATH "/usr/local/share/cmake/cppzmq")

# Find cppzmq package
find_package(cppzmq REQUIRED)

# DevMem source files
set(DEV_MEM_SRC srcs/DevMem.cpp)
set(DEV_MEM_HEADER include/DevMem.hpp) # Assuming headers are in 'include' directory

# FpgaRegDict source files
set(FPGA_REG_DICT_SRC srcs/FpgaRegDict.cpp)
set(FPGA_REG_DICT_HEADER include/FpgaRegDict.hpp) # Assuming headers are in 'include' directory

# REG source files
set(REG_SRC srcs/reg.cpp)
set(REG_HEADER include/reg.hpp) # Assuming headers are in 'include' directory

# FPGAREG source files
set(FPGAREG_SRC srcs/FpgaReg.cpp)
set(FPGAREG_HEADER include/FpgaReg.hpp) # Assuming headers are in 'include' directory

# SPI source files
set(SPI_SRC srcs/Spi.cpp)
set(SPI_HEADER include/Spi.hpp) # Assuming headers are in 'include' directory

# SPYBUFFER source files
set(SPYBUFFER_SRC srcs/SpyBuffer.cpp)
set(SPYBUFFER_HEADER include/SpyBuffer.hpp) # Assuming headers are in 'include' directory

# AFE source files
set(AFE_SRC srcs/Afe.cpp)
set(AFE_HEADER include/Afe.hpp) # Assuming headers are in 'include' directory

# FRONTEND source files
set(FRONTEND_SRC srcs/FrontEnd.cpp)
set(FRONTEND_HEADER include/FrontEnd.hpp) # Assuming headers are in 'include' directory

# ENDPOINT source files
set(ENDPOINT_SRC srcs/Endpoint.cpp)
set(ENDPOINT_HEADER include/Endpoint.hpp) # Assuming headers are in 'include' directory

# DAC source files
set(DAC_SRC srcs/Dac.cpp)
set(DAC_HEADER include/Dac.hpp) # Assuming headers are in 'include' directory

# DAPHNE source files
set(DAPHNE_SRC srcs/Daphne.cpp)
set(DAPHNE_HEADER include/Daphne.hpp) # Assuming headers are in 'include' directory

# Publisher, Subscriber, and SRV source files
set(PUBLISHER_SRC srcs/publisher.cpp)
set(SUBSCRIBER_SRC srcs/subscriber.cpp)
set(SRV_SRC srcs/srv.cpp)
set(SRV_REG_SRC srcs/srv_reg.cpp)
set(DAPHNE_TEST_SRC srcs/daphne_test.cpp)

# Include directories
include_directories(include) # Add your 'include' directory for custom headers

# Create executables and link libraries
add_executable(publisher ${PUBLISHER_SRC} ${DEV_MEM_SRC})
target_link_libraries(publisher PRIVATE cppzmq)

add_executable(subscriber ${SUBSCRIBER_SRC} ${DEV_MEM_SRC})
target_link_libraries(subscriber PRIVATE cppzmq)

add_executable(srv ${SRV_SRC}
                   ${DEV_MEM_SRC}
                   ${FPGA_REG_DICT_SRC}
                   ${REG_SRC}
                   ${FPGAREG_SRC}
                   ${SPI_SRC}
                   ${SPYBUFFER_SRC}
                   ${AFE_SRC}
                   ${FRONTEND_SRC}
                   ${ENDPOINT_SRC}
                   ${DAC_SRC}
                   ${DAPHNE_SRC})
add_executable(srv_reg ${SRV_REG_SRC}
					   ${DEV_MEM_SRC}
					   ${FPGA_REG_DICT_SRC}
					   ${REG_SRC}
					   ${FPGAREG_SRC}
					   ${SPI_SRC}
					   ${SPYBUFFER_SRC}
					   ${AFE_SRC}
					   ${FRONTEND_SRC}
					   ${ENDPOINT_SRC}
					   ${DAC_SRC}
					   ${DAPHNE_SRC})
add_executable(daphne_test ${DAPHNE_TEST_SRC}
					   ${DEV_MEM_SRC}
					   ${FPGA_REG_DICT_SRC}
					   ${REG_SRC}
					   ${FPGAREG_SRC}
					   ${SPI_SRC}
					   ${SPYBUFFER_SRC}
					   ${AFE_SRC}
					   ${FRONTEND_SRC}
					   ${ENDPOINT_SRC}
					   ${DAC_SRC}
					   ${DAPHNE_SRC})					  
target_link_libraries(srv PRIVATE cppzmq)
target_link_libraries(srv_reg PRIVATE cppzmq)
target_link_libraries(daphne_test PRIVATE cppzmq)

# Include cppzmq headers
target_include_directories(publisher PRIVATE ${cppzmq_INCLUDE_DIRS})
target_include_directories(subscriber PRIVATE ${cppzmq_INCLUDE_DIRS})
target_include_directories(srv PRIVATE ${cppzmq_INCLUDE_DIRS})
target_include_directories(srv_reg PRIVATE ${cppzmq_INCLUDE_DIRS})
target_include_directories(daphne_test PRIVATE ${cppzmq_INCLUDE_DIRS})