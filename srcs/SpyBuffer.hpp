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
    uint32_t getData(const uint32_t& afe, const uint32_t& ch, const uint32_t& sample = 0);
    double getOutputVoltage(const uint32_t& afe, const uint32_t& ch, const uint32_t& sample = 0);
    
private:
    std::unique_ptr<FpgaReg> fpgaReg;
};

#endif // SPYBUFFER_HPP