#ifndef SPYBUFFER_HPP
#define SPYBUFFER_HPP

#include <cstdint>
#include <string>
#include <vector>
#include <stdexcept>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <chrono>
#include <thread>

#include "FpgaReg.hpp"

class SpyBuffer {
public:
    // Constructor
    SpyBuffer();

    // Destructor
    ~SpyBuffer();

    uint32_t getFrameClock(const uint32_t& afe, const uint32_t& sample = 0);
    uint32_t getData(const uint32_t& sample = 0) const;
    uint32_t getMappedData(uint32_t sample = 0) const;
    void cacheSpyBufferRegister(const uint32_t& afe, const uint32_t& ch);
    double getOutputVoltage(const uint32_t& sample = 0);
    void setCurrentMappedChannelIndex(uint32_t index);
    
private:
    std::unique_ptr<FpgaReg> fpgaReg;
    std::array<const uint32_t*, 40> channel_ptrs;
    uint32_t current_channel_index;

    void mapToArraySpyBufferRegisters();
};

#endif // SPYBUFFER_HPP