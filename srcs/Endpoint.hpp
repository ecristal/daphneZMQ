#ifndef ENDPOINT_HPP
#define ENDPOINT_HPP

#include <cstdint>
#include <string>
#include <vector>
#include <stdexcept>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <chrono>
#include <thread>
#include <unordered_map>

#include "FpgaReg.hpp"

class Endpoint {
public:
    // Constructor
    Endpoint();

    // Destructor
    ~Endpoint();
    
    uint32_t getClockSource();
    uint32_t setClockSource(const uint32_t &clockSource);
    uint32_t setClockSourceLocal();
    uint32_t setClockSourceEndpoint();
    uint32_t getMmcmReset();
    uint32_t setMmcmReset(const uint32_t &reset);
    uint32_t doMmcmReset();
    uint32_t getSoftReset();
    uint32_t setSoftReset(const uint32_t &reset);   
    uint32_t doSoftReset();    
    uint32_t getClockStatus(const uint32_t &mmcm);
    uint32_t checkClockStatus();
    uint32_t getAddress();
    uint32_t setAddress(const uint32_t &address);
    uint32_t getReset();
    uint32_t setReset(const uint32_t &reset);
    uint32_t doReset();
    uint32_t getTimestampOk();
    uint32_t getFsmStatus();
    uint32_t checkEndpointStatus(const uint32_t &expTimestampOk=0x1, const uint32_t &expFsmStatus=0x8);
    uint32_t initEndpoint(const uint32_t &address=0x20, const uint32_t &clockSource = 1);

private:
    std::unique_ptr<FpgaReg> fpgaReg;

    uint32_t CLOCK_SOURCE_LOCAL;
    uint32_t CLOCK_SOURCE_ENDPOINT;
};

#endif // ENDPOINT_HPP