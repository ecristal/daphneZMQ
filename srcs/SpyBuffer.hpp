#ifndef SPYBUFFER_HPP
#define SPYBUFFER_HPP

#include <arm_neon.h>
#include <cstdint>
#include <cstddef>
#include <string>
#include <vector>
#include <stdexcept>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <chrono>
#include <thread>
#include <array>

#include "FpgaReg.hpp"

class SpyBuffer {
public:
    // Constructor
    SpyBuffer();

    // Destructor
    ~SpyBuffer();

    uint32_t getFrameClock(const uint32_t& afe, const uint32_t& sample = 0);
    uint32_t getData(const uint32_t& sample = 0) const;
    
    inline uint32_t getMappedData(uint32_t sample) const {
        const uint32_t* ptr = channel_ptrs[this->current_channel_index];
        uint32_t raw_word = ptr[sample / 2];
        uint32_t shift = 2 + 16 * (sample & 1);
        return (raw_word >> shift) & 0x3FFF;
    }

    void cacheSpyBufferRegister(const uint32_t& afe, const uint32_t& ch);
    double getOutputVoltage(const uint32_t& sample = 0);
    void setCurrentMappedChannelIndex(uint32_t index);
    const uint32_t* getCurrentChannelDataPointer() const;
    const uint32_t* getChannelDataPointer(uint32_t index) const;
    void extractMappedDataBulk(uint32_t* output, uint32_t numberOfSamples) const;
    void extractMappedDataBulkSIMD(uint32_t* dst, uint32_t nSamples);
    void extractMappedDataBulkSIMD(uint32_t* dst, uint32_t nSamples, uint32_t channel_index);

private:
    std::unique_ptr<FpgaReg> fpgaReg;
    std::array<const uint32_t*, 40> channel_ptrs;
    uint32_t current_channel_index;

    void mapToArraySpyBufferRegisters();
};

#endif // SPYBUFFER_HPP