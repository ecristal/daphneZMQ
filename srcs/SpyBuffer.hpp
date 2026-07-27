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
#include <functional>
#include <mutex>
#include <optional>
#include "FpgaReg.hpp"

class SpyBuffer {
public:
    using TimestampKey = std::array<uint16_t, 4>;

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
    TimestampKey getTimestampKey(const uint32_t& sample = 0) const;
    TimestampKey acquireFreshMappedData(
        uint32_t* dst,
        uint32_t nSamples,
        const std::vector<uint32_t>& channel_indices,
        const std::function<void()>& issue_trigger = {});
    static uint64_t packTimestamp(const TimestampKey& timestamp);

private:
    std::unique_ptr<FpgaReg> fpgaReg;
    std::array<const uint32_t*, 40> channel_ptrs;
    std::array<const volatile uint32_t*, 4> timestamp_ptrs;
    uint32_t current_channel_index;
    std::mutex acquisition_mutex;
    std::optional<TimestampKey> last_delivered_timestamp;
    std::chrono::milliseconds trigger_wait_timeout;
    std::chrono::microseconds timestamp_poll_interval;

    void mapToArraySpyBufferRegisters();
    void mapTimestampRegisters();
    TimestampKey readStableTimestamp(
        const std::chrono::steady_clock::time_point& deadline) const;
    bool waitExpired(const std::chrono::steady_clock::time_point& deadline) const;
};

#endif // SPYBUFFER_HPP
