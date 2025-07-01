#include <iostream>
#include <zmq.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <stdexcept>
#include <vector>
#include <numeric>
#include <cmath>
#include <map>
#include <string>

#include "Daphne.hpp"
#include "protobuf/daphneV3_high_level_confs.pb.h"

int main(int argc, char* argv[]) {

    std::map<std::string, std::string> args;
    std::string ip_address;
    int port;

    // Parse arguments
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 < argc) { // Ensure value exists
            args[argv[i]] = argv[i + 1];
        }
    }

    // Validate and extract -ip
    if (args.find("-ip") != args.end()) {
        ip_address = args["-ip"];
        std::cout << "IP Address: " << ip_address << std::endl;
    } else {
        std::cerr << "Error: Missing -ip parameter.\n";
        std::cerr << "Usage: ./daphne_test -ip <IP_ADDRESS> -port <PORT>\n";
        return 1;
    }

    // Validate and extract -port
    if (args.find("-port") != args.end()) {
        try {
            port = std::stoi(args["-port"]); // Convert string to int
            if (port < 1 || port > 65535) {
                throw std::out_of_range("Port out of range");
            }
            std::cout << "Port: " << port << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "Error: Invalid port number. " << e.what() << std::endl;
            return 1;
        }
    } else {
        std::cerr << "Error: Missing -port parameter.\n";
        std::cerr << "Usage: ./daphne_test -ip <IP_ADDRESS> -port <PORT>\n";
        return 1;
    }
    
    Daphne daphne;
    std::cout<< "Reseting AFEs" << std::endl;
    //daphne.getAfe()->doReset();
    std::cout<< "Reseting AFEs ...done" << std::endl;
    std::cout<< "Powerdown AFEs" << std::endl;
    daphne.getAfe()->setPowerState(0);
    std::cout<< "Powerdown AFEs ...done" << std::endl;

    std::vector<uint32_t> afeList = {0, 1, 2, 3, 4};

    double vGain = 0.75;
    uint32_t vOffset = 2234;
    uint32_t vTrim = 0;

    std::unordered_map<uint32_t, uint32_t> afeRegDict = {
        {0x02, 0x0000},
        {0x03, 0x2000},
        {0x04, 0x0008},
        {0x0A, 0x0100}, 
        {0x05, 0x35A5}, 
        {0x33, 0x0058}, 
        {0x34, 0x5200},     
    }; 

    for(auto afe : afeList){
       for(uint32_t i = 0; i < 4; i++){
           daphne.getDac()->setDacTrimOffset("Offset", afe, i, vOffset, i, vOffset);
           daphne.getDac()->setDacTrimOffset("Trim", afe, i, vTrim, i, vTrim);
       }
       daphne.getDac()->setDacGain(afe,vGain);
       daphne.getAfe()->initAFE(afe,afeRegDict);
    }

    daphne.getAfe()->setPowerState(1);
    daphne.getFrontEnd()->doResetDelayCtrl();
    daphne.getFrontEnd()->doResetSerDesCtrl();
    daphne.getFrontEnd()->setEnableDelayVtc(0);

    for(auto afe : afeList){
       daphne.setBestDelay(afe);
       daphne.setBestBitslip(afe);
    }

    daphne.getFrontEnd()->setEnableDelayVtc(1);

    for(auto afe : afeList){
        std::cout << "AFE: " << afe << ", DELAY: " << std::dec << daphne.getFrontEnd()->getDelay(afe) << std::endl;
        std::cout << "AFE: " << afe << ", BITSLIP: " << std::dec << daphne.getFrontEnd()->getBitslip(afe) << std::endl;
    }

    afeList = {1};
    std::vector<uint32_t> chList = {0};

    uint32_t dataLen = 2048;
    std::vector<double> data(dataLen,0.0);

    void *context = zmq_ctx_new();
    void *socket = zmq_socket(context, ZMQ_REP);  // REP = Reply socket
    //zmq_bind(socket, "tcp://193.206.157.36:9000");
    ip_address = "tcp://" + ip_address + ":" + std::to_string(port); 
    zmq_bind(socket, ip_address.c_str());
    std::cout << "srv bound to " + ip_address << std::endl;

    while(1){
        char buffer[256] = {0};
        int bytes_received = zmq_recv(socket, buffer, 255, 0);
        buffer[bytes_received] = '\0';
        // Parse command
        char command[16] = {0};
        uint32_t offset = 0, value = 0;
        int num_arg = sscanf(buffer, "%15s %x %x", command, &offset, &value);
        try{
            if (strcmp(command, "write") == 0) {
                if(num_arg < 3){
                    zmq_send(socket, "ERROR", 5, 0);
                    continue;
                }
            } else if (strcmp(command, "read") == 0) {
                if(num_arg < 2){
                    zmq_send(socket, "ERROR", 5, 0);
                    continue;
                }
                std::cout << "Received read command with parameters: " << command << " " << std::hex << offset << std::endl;
                std::cout << "Sending data ... " << std::endl;
                for(int messages_to_send = 0; messages_to_send < offset; messages_to_send++){
                    for(uint32_t afe : afeList){
                        for(uint32_t ch : chList){
                            //std::cout << "AFE: " << afe << " ch: " << ch << std::endl;
                            daphne.getFrontEnd()->doTrigger();
                            for(uint32_t i = 0; i < dataLen; i++){
                                data[i] = daphne.getSpyBuffer()->getOutputVoltage(afe,ch,i);
                            }
                        }
                    }
                    zmq_msg_t message;
                    zmq_msg_init_size(&message, data.size() * sizeof(double));
                    memcpy(zmq_msg_data(&message), data.data(), data.size() * sizeof(double));

                    int send_flag = (messages_to_send < offset - 1) ? ZMQ_SNDMORE : 0; // Keep sending until the last message
                    zmq_msg_send(&message, socket, send_flag);
                    zmq_msg_close(&message);
                }
                std::cout << "Finished sending data ... " << std::endl;
                //std::cout << "Message sent: " << buffer << offset << std::endl;
            } else {
                zmq_send(socket, "ERROR", 5, 0);
            }
        }catch (const std::runtime_error& e) {
            std::cerr << "Caught an exception: " << e.what() << std::endl;
        }
    }

    double sum = std::accumulate(data.begin(), data.end(), 0.0);
    double mean = sum / ((double)data.size());

    double sq_sum = std::accumulate(data.begin(), data.end(), 0.0, 
        [mean](double acc, double x) { return acc + (x - mean) * (x - mean); });
    double std = std::sqrt(sq_sum / data.size() - mean * mean);

    std::cout << "vector: "  << std::endl;

    for(int i = 0; i < data.size(); i++){
        std::cout << "data[" << i << "] = " << data[i] << std::endl;
    }

    std::cout << "Mean: " << mean << " std: " << std << std::endl;

    // Clean up
    zmq_close(socket);
    zmq_ctx_destroy(context);
    return 0;
}