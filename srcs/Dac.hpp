#ifndef DAC_HPP
#define DAC_HPP

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
#include <exception>
#include <map>
#include <tuple>

#include "Spi.hpp"

class Dac {
public:
    // Constructor
    Dac();

    // Destructor
    ~Dac();

    uint32_t setDacGain(const uint32_t& afe, const uint32_t& value);
    uint32_t setDacBias(const uint32_t& afe, const uint32_t& value);
    uint32_t setDacHvBias(const uint32_t& value, const bool& gain = false, const bool& buffer = false);
    uint32_t setDacTrim(const uint32_t& afe,const uint32_t& ch,const uint32_t& value, const bool& gain, const bool& buffer);
    uint32_t setDacOffset(const uint32_t& afe,const uint32_t& ch,const uint32_t& value, const bool& gain, const bool& buffer);
    uint32_t setDacTrimOffset(const std::string& what, const uint32_t& afe,const uint32_t& channelH,const uint32_t& valueH,const uint32_t& channelL,const uint32_t& valueL, const bool& gain = false, const bool& buffer = false);
    uint32_t setBiasEnable(const bool &enable);

private:
    using TupleEntry_GainBias = std::tuple<std::string, uint32_t, bool, bool>;
    using TupleEntry_ChMapping = std::tuple<std::string, uint32_t>;

    std::unique_ptr<Spi> spi;

    std::unordered_map<std::string, std::unordered_map<uint32_t, uint32_t>> channelValues;
    // This mapping has to be verified!!!!
    std::map<uint32_t, TupleEntry_GainBias> GAIN_MAPPING = {
        {0, {"U50", 0, false, false}}, // chip, chip_channel, chip_channel_gain, chip_channel_buffer
        {1, {"U50", 1, false, false}},
        {2, {"U50", 2, false, false}},
        {3, {"U50", 3, false, false}},
        {4, {"U5", 1, false, false}}
    };
    std::map<uint32_t, TupleEntry_GainBias> BIAS_MAPPING = {
        {0, {"U53", 0, false, false}}, // chip, chip_channel, chip_channel_gain, chip_channel_buffer
        {1, {"U53", 1, false, false}},
        {2, {"U53", 2, false, false}},
        {3, {"U53", 3, false, false}},
        {4, {"U5", 0, false, false}}
    };
    std::map<uint32_t, TupleEntry_ChMapping> CHANNEL_MAPPING = {
        {0, {"L", 0}},
        {1, {"L", 1}},
        {2, {"L", 2}},
        {3, {"L", 3}},
        {4, {"H", 0}},
        {5, {"H", 1}},
        {6, {"H", 2}},
        {7, {"H", 3}}
    };

    bool isBusy();
    bool waitNotBusy(const double& timeout = 0.01);
    uint32_t triggerWrite();
    uint32_t setDacGeneral(const std::string& chip, const uint32_t& channel, const bool& gain = false, const bool& buffer = false, const uint32_t& value = 0);
    uint32_t setDacGainBias(const std::string& what, const uint32_t& afe, const uint32_t& value);
    uint32_t findCompanionChannelValue(const uint32_t& ch);
    uint32_t updateCurrentRegister(const std::string& reg_name, const uint32_t& ch, const uint32_t& value, const bool& gain, const bool& buffer);
};

#endif // DACTRIMOFFSET_HPP