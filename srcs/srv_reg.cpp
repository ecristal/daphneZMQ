#include <iostream>
#include <zmq.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <stdexcept>

#include "DevMem.hpp"
#include "FpgaRegDict.hpp"
#include "reg.hpp"

#define AXI_BASE_ADDR 0x80000000  // Adjust to DAPHNE AXI base address
#define AXI_SIZE      0x7FFFFFFF  // Adjust to DAPHNE AXI memory size

void *axi_map = NULL;

int main() {
    // Map AXI registers
    DevMem devmem(AXI_BASE_ADDR);
    devmem.map_memory(AXI_SIZE);
    //FpgaRegDict reg_dict;
    //reg test_reg(AXI_BASE_ADDR,AXI_SIZE,reg_dict);
    // Initialize ZeroMQ
    void *context = zmq_ctx_new();
    void *socket = zmq_socket(context, ZMQ_REP);  // REP = Reply socket
    zmq_bind(socket, "tcp://193.206.157.36:9000");  // Bind to port 5555
    std::cout << "srv bound to tcp://193.206.157.36:9000" << std::endl;

    while (1) {
        char buffer[256] = {0};
        int bytes_received = zmq_recv(socket, buffer, 255, 0);
        buffer[bytes_received] = '\0';
        // Parse command
        char command[16] = {0};
        uint32_t offset = 0, value = 0;
        int num_arg = sscanf(buffer, "%15s %x %x", command, &offset, &value);
        if(num_arg < 2){
            zmq_send(socket, "ERROR", 5, 0);
            continue;
        }
        try{
            if (strcmp(command, "write") == 0) {
                if(num_arg < 3){
                    zmq_send(socket, "ERROR", 5, 0);
                    continue;
                }
                //write_register(offset, value);
                std::cout << "Received write command with parameters: " << command << " " << std::hex << offset << " " << value << std::endl;
                //devmem.changeBaseAddr(offset,AXI_SIZE);
                std::vector<uint32_t> value_vector(1);
                value_vector[0] = value;
                devmem.write(offset,value_vector);
                auto data = devmem.read(offset, 1);
                uint32_t result = data[0];
                //uint32_t result = test_reg.WriteRegister("endpointClockControl",value_vector);
                std::cout << "Result: " << std::hex << result << std::endl;
                if(result == value){
                    zmq_send(socket, "OK: The value was written correctly", 35, 0);
                }else{
                    zmq_send(socket, "ERROR: Value was not correctly written", 38, 0);
                }
            } else if (strcmp(command, "read") == 0) {
                if(num_arg < 2){
                    zmq_send(socket, "ERROR", 5, 0);
                    continue;
                }\
                std::cout << "Received read command with parameters: " << command << " " << std::hex << offset << std::endl;
                //devmem.changeBaseAddr(offset,AXI_SIZE);
                auto data = devmem.read(offset, 1);
                uint32_t result = data[0];
                std::cout << "Result: " << std::hex << result << std::endl;
                snprintf(buffer, sizeof(buffer), "%08x", result);
                zmq_send(socket, buffer, strlen(buffer), 0);
                std::cout << "Message sent: " << buffer << offset << std::endl;
            } else {
                zmq_send(socket, "ERROR", 5, 0);
            }
        }catch (const std::runtime_error& e) {
            std::cerr << "Caught an exception: " << e.what() << std::endl;
        }
    }

    zmq_close(socket);
    zmq_ctx_destroy(context);
    munmap(axi_map, AXI_SIZE);

    return 0;
}