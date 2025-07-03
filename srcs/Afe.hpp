#ifndef AFE_HPP
#define AFE_HPP

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
#include <algorithm>

#include "Spi.hpp"

class Afe {
public:
    // Constructor
    Afe();

    // Destructor
    ~Afe();

    using BitField = std::unordered_map<uint32_t, std::pair<int, int>>;
    
    uint32_t setReset(const uint32_t& reset);
    uint32_t doReset();
    uint32_t setPowerState(const uint32_t& powerstate);
    uint32_t getPowerState();
    uint32_t setRegister(const uint32_t& afe, const uint32_t& register_, const uint32_t& value);
    uint32_t getRegister(const uint32_t& afe, const uint32_t& register_);
    uint32_t initAFE(const uint32_t& afe, const std::unordered_map<uint32_t, uint32_t> &regDict);
    uint32_t setAFEFunction(const uint32_t& afe, const std::string& functionName, const uint16_t& value);
    uint32_t getAFEFunction(const uint32_t& afe, const std::string& functionName);
    void updateAfeRegDict(const uint32_t& afe, std::unordered_map<uint32_t, uint32_t> &dict, const std::string& functionName);
    uint32_t getAFEFunctionValueFromRegDict(const uint32_t& afe, std::unordered_map<uint32_t, uint32_t> &dict, const std::string& functionName);
    void setRegisterList(const std::vector<uint32_t> reg_list) {this->register_list = reg_list;}

private:
    std::unique_ptr<Spi> spi;
    
    std::vector<uint32_t> register_list;
    // {FUNCTION_NAME, {REGISTER_ADDR, {BITH, BITL}}}
    std::unordered_map<std::string, Afe::BitField> afeFunctionDict = { 
        {"SOFTWARE_RESET", {{0, {0, 0}}}},
        {"REGISTER_READOUT_ENABLE", {{0, {1, 1}}}},
        {"ADC_COMPLETE_PDN", {{1, {0, 0}}}},
        {"LVDS_OUTPUT_DISABLE", {{1, {1, 1}}}},
        {"ADC_PDN_CH", {{1, {9, 2}}}},
        {"PARTIAL_PDN", {{1, {10, 10}}}},
        {"LOW_FREQUENCY_NOISE_SUPRESSION", {{1, {11, 11}}}},
        {"EXT_REF", {{1 , {13, 13}}}},
        {"LVDS_OUTPUT_RATE_2X", {{1, {12, 14}}}},
        {"SINGLE-ENDED_CLK_MODE", {{1, {15, 15}}}},
        {"POWER-DOWN_LVDS", {{2, {10, 3}}}},
        {"AVERAGING_ENABLE", {{2, {11, 11}}}},
        {"LOW_LATENCY", {{2, {12, 12}}}},
        {"TEST_PATTERN_MODES", {{2, {15, 13}}}},
        {"INVERT_CHANNELS", {{3, {7, 0}}}},
        {"CHANNEL_OFFSET_SUBSTRACTION_ENABLE", {{3, {8, 8}}}},
        {"DIGITAL_GAIN_ENABLE", {{3, {12, 12}}}},
        {"SERIALIZED_DATA_RATE", {{3, {14, 13}}}},
        {"ENABLE_EXTERNAL_REFERENCE_MODE", {{3, {15, 15}}}},
        {"ADC_RESOLUTION_RESET", {{4, {1, 1}}}},
        {"ADC_OUTPUT_FORMAT", {{4, {3, 3}}}},
        {"LSB_MSB_FIRST", {{4, {4 ,4}}}},
        {"CUSTOM_PATTERN", {{5, {13, 0}}}},
        {"SYNC_PATTERN", {{10, {8, 8}}}},
        {"OFFSET_CH1", {{13, {9, 0}}}},
        {"DIGITAL_GAIN_CH1", {{13, {15, 11}}}},
        {"OFFSET_CH2", {{15, {9, 0}}}},
        {"DIGITAL_GAIN_CH2", {{15, {15, 11}}}},
        {"OFFSET_CH3", {{17, {9, 0}}}},
        {"DIGITAL_GAIN_CH3", {{17, {15, 11}}}},
        {"OFFSET_CH4", {{19, {9, 0}}}},
        {"DIGITAL_GAIN_CH4", {{19, {15, 11}}}},
        {"DIGITAL_HPF_FILTER_ENABLE_CH1-4", {{21, {0, 0}}}},
        {"DIGITAL_HPF_FILTER_K_CH1-4", {{21, {4, 1}}}},
        {"OFFSET_CH8", {{25, {9, 0}}}},
        {"DIGITAL_GAIN_CH8", {{25, {15, 11}}}},
        {"OFFSET_CH7", {{27, {9, 0}}}},
        {"DIGITAL_GAIN_CH7", {{27, {15, 11}}}},
        {"OFFSET_CH6", {{29, {9, 0}}}},
        {"DIGITAL_GAIN_CH6", {{29, {15, 11}}}},
        {"OFFSET_CH5", {{31, {9, 0}}}},
        {"DIGITAL_GAIN_CH5", {{31, {15, 11}}}},
        {"DIGITAL_HPF_FILTER_ENABLE_CH5-8", {{33, {0, 0}}}},
        {"DIGITAL_HPF_FILTER_K_CH5-8", {{33, {4, 1}}}},
        {"DITHER", {{66, {15, 15}}}},
        {"PGA_CLAMP_-6dB", {{50, {10, 10}}}},
        {"LPF_PROGRAMMABILITY", {{51, {3, 1}}}},
        {"PGA_INTEGRATOR_DISABLE", {{51, {4, 4}}}},
        {"PGA_CLAMP_LEVEL", {{51, {7, 5}}}},
        {"PGA_GAIN_CONTROL", {{51, {13, 13}}}},
        {"ACTIVE_TERMINATION_INDIVIDUAL_RESISTOR_CNTL", {{52, {4, 0}}}},
        {"ACTIVE_TERMINATION_INDIVIDUAL_RESISTOR_ENABLE", {{52, {5, 5}}}},
        {"PRESET_ACTIVE_TERMINATIONS", {{52, {7, 6}}}},
        {"ACTIVE_TERMINATION_ENABLE", {{52, {8, 8}}}},
        {"LNA_INPUT_CLAMP_SETTING", {{52, {10, 9}}}},
        {"LNA_INTEGRATOR_DISABLE", {{52, {12, 12}}}},
        {"LNA_GAIN", {{52, {14, 13}}}},
        {"LNA_INDIVIDUAL_CH_CNTL", {{52, {15, 15}}}},
        {"PDN_CH", {{53, {7, 0}}}},
        {"LOW_POWER", {{53, {10, 10}}}},
        {"MED_POWER", {{53, {11, 11}}}},
        {"PDN_VCAT_PGA", {{53, {12, 12}}}},
        {"PDN_LNA", {{53, {13, 13}}}},
        {"VCA_PARTIAL_PDN", {{53, {14, 14}}}},
        {"VCA_COMPLETE_PDN", {{53, {15, 15}}}},
        {"CW_SUM_AMP_GAIN_CNTL", {{54, {4, 0}}}},
        {"CW_16X_CLK_SEL", {{54, {5, 5}}}},
        {"CW_1X_CLK_SEL", {{54, {6, 6}}}},
        {"CW_TGC_SEL", {{54, {8, 8}}}}, 
        {"CW_SUM_AMP_ENABLE", {{54, {9, 9}}}},
        {"CW_CLK_MODE_SEL", {{54, {11, 10}}}},
        {"CH1_CW_MIXER_PHASE", {{55, {3 ,0}}}},
        {"CH2_CW_MIXER_PHASE", {{55, {7, 4}}}},
        {"CH3_CW_MIXER_PHASE", {{55, {11, 8}}}},
        {"CH4_CW_MIXER_PHASE", {{55, {15, 12}}}},
        {"CH5_CW_MIXER_PHASE", {{56, {3, 0}}}},
        {"CH6_CW_MIXER_PHASE", {{56, {7, 4}}}},
        {"CH7_CW_MIXER_PHASE", {{56, {11, 8}}}},
        {"CH8_CW_MIXER_PHASE", {{56, {15, 12}}}},
        {"CH1_LNA_GAIN_CNTL", {{57, {1, 0}}}},
        {"CH2_LNA_GAIN_CNTL", {{57, {3, 2}}}},
        {"CH3_LNA_GAIN_CNTL", {{57, {5, 4}}}},
        {"CH4_LNA_GAIN_CNTL", {{57, {7, 6}}}},
        {"CH5_LNA_GAIN_CNTL", {{57, {9, 8}}}},
        {"CH6_LNA_GAIN_CNTL", {{57, {11, 10}}}},
        {"CH7_LNA_GAIN_CNTL", {{57, {13, 12}}}},
        {"CH8_LNA_GAIN_CNTL", {{57, {15, 14}}}},
        {"HPF_LNA", {{59, {3, 2}}}},
        {"DIG_TGC_ATT_GAIN", {{59, {6, 4}}}},
        {"DIG_TGC_ATT", {{59, {7, 7}}}},
        {"CW_SUM_AMP_PDN", {{59, {8, 8}}}},
        {"PGA_TEST_MODE", {{59 , {9, 9}}}}
};

std::unordered_map<std::string, std::vector<uint16_t>> afeFunctionAvailableOptionsDict = { 
    {"SOFTWARE_RESET", {0, 1}},
    {"REGISTER_READOUT_ENABLE", {0, 1}},
    {"ADC_COMPLETE_PDN", {0, 1}},
    {"LVDS_OUTPUT_DISABLE", {0, 1}},
    {"ADC_PDN_CH", {0, 0xFF}},
    {"PARTIAL_PDN", {0, 1}},
    {"LOW_FREQUENCY_NOISE_SUPRESSION", {0, 1}},
    {"EXT_REF", {0, 1}},
    {"LVDS_OUTPUT_RATE_2X", {0, 1}},
    {"SINGLE-ENDED_CLK_MODE", {0, 1}},
    {"POWER-DOWN_LVDS", {0, 1}},
    {"AVERAGING_ENABLE", {0, 1}},
    {"LOW_LATENCY", {0, 1}},
    {"TEST_PATTERN_MODES", {0, 0x7}},
    {"INVERT_CHANNELS", {0, 0xFF}},
    {"CHANNEL_OFFSET_SUBSTRACTION_ENABLE", {0, 1}},
    {"DIGITAL_GAIN_ENABLE", {0, 1}},
    {"SERIALIZED_DATA_RATE", {0, 0x3}},
    {"ENABLE_EXTERNAL_REFERENCE_MODE", {0, 1}},
    {"ADC_RESOLUTION_RESET", {0, 1}},
    {"ADC_OUTPUT_FORMAT", {0, 1}},
    {"LSB_MSB_FIRST", {0, 1}},
    {"CUSTOM_PATTERN", {0, 0x3FFF}},
    {"SYNC_PATTERN", {0, 1}},
    {"OFFSET_CH1", {0, 0x3FF}},
    {"DIGITAL_GAIN_CH1", {0, 0x1F}},
    {"OFFSET_CH2", {0, 0x3FF}},
    {"DIGITAL_GAIN_CH2", {0, 0x1F}},
    {"OFFSET_CH3", {0, 0x3FF}},
    {"DIGITAL_GAIN_CH3", {0, 0x1F}},
    {"OFFSET_CH4", {0, 0x3FF}},
    {"DIGITAL_GAIN_CH4", {0, 0x1F}},
    {"DIGITAL_HPF_FILTER_ENABLE_CH1-4", {0, 0}},
    {"DIGITAL_HPF_FILTER_K_CH1-4", {2, 10}},
    {"OFFSET_CH8", {0, 0x3FF}},
    {"DIGITAL_GAIN_CH8", {0, 0x1F}},
    {"OFFSET_CH7", {0, 0x3FF}},
    {"DIGITAL_GAIN_CH7", {0, 0x1F}},
    {"OFFSET_CH6", {0, 0x3FF}},
    {"DIGITAL_GAIN_CH6", {0, 0x1F}},
    {"OFFSET_CH5", {0, 0x3FF}},
    {"DIGITAL_GAIN_CH5", {0, 0x1F}},
    {"DIGITAL_HPF_FILTER_ENABLE_CH5-8", {0, 1}},
    {"DIGITAL_HPF_FILTER_K_CH5-8", {2, 10}},
    {"DITHER", {0, 1}},
    {"PGA_CLAMP_-6dB", {0, 1}},
    {"LPF_PROGRAMMABILITY", {0, 2, 3, 4}},
    {"PGA_INTEGRATOR_DISABLE", {0, 1}},
    {"PGA_CLAMP_LEVEL", {0, 7}},
    {"PGA_GAIN_CONTROL", {0, 1}},
    {"ACTIVE_TERMINATION_INDIVIDUAL_RESISTOR_CNTL", {0, 0x1F}},
    {"ACTIVE_TERMINATION_INDIVIDUAL_RESISTOR_ENABLE", {0, 1}},
    {"PRESET_ACTIVE_TERMINATIONS", {0, 3}},
    {"ACTIVE_TERMINATION_ENABLE", {0, 1}},
    {"LNA_INPUT_CLAMP_SETTING", {0, 3}},
    {"LNA_INTEGRATOR_DISABLE", {0, 1}},
    {"LNA_GAIN", {0, 3}},
    {"LNA_INDIVIDUAL_CH_CNTL", {0, 1}},
    {"PDN_CH", {0, 0xFF}},
    {"LOW_POWER", {0, 1}},
    {"MED_POWER", {0, 1}},
    {"PDN_VCAT_PGA", {0, 1}},
    {"PDN_LNA", {0, 1}},
    {"VCA_PARTIAL_PDN", {0, 1}},
    {"VCA_COMPLETE_PDN", {0, 1}},
    {"CW_SUM_AMP_GAIN_CNTL", {0, 1, 2, 4, 8, 16}},
    {"CW_16X_CLK_SEL", {0, 1}},
    {"CW_1X_CLK_SEL", {0, 1}},
    {"CW_TGC_SEL", {0, 1}}, 
    {"CW_SUM_AMP_ENABLE", {0, 1}},
    {"CW_CLK_MODE_SEL", {0, 3}},
    {"CH1_CW_MIXER_PHASE", {0, 0xF}},
    {"CH2_CW_MIXER_PHASE", {0, 0xF}},
    {"CH3_CW_MIXER_PHASE", {0, 0xF}},
    {"CH4_CW_MIXER_PHASE", {0, 0xF}},
    {"CH5_CW_MIXER_PHASE", {0, 0xF}},
    {"CH6_CW_MIXER_PHASE", {0, 0xF}},
    {"CH7_CW_MIXER_PHASE", {0, 0xF}},
    {"CH8_CW_MIXER_PHASE", {0, 0xF}},
    {"CH1_LNA_GAIN_CNTL", {0, 3}},
    {"CH2_LNA_GAIN_CNTL", {0, 3}},
    {"CH3_LNA_GAIN_CNTL", {0, 3}},
    {"CH4_LNA_GAIN_CNTL", {0, 3}},
    {"CH5_LNA_GAIN_CNTL", {0, 3}},
    {"CH6_LNA_GAIN_CNTL", {0, 3}},
    {"CH7_LNA_GAIN_CNTL", {0, 3}},
    {"CH8_LNA_GAIN_CNTL", {0, 3}},
    {"HPF_LNA", {0, 3}},
    {"DIG_TGC_ATT_GAIN", {0, 0x7}},
    {"DIG_TGC_ATT", {0, 1}},
    {"CW_SUM_AMP_PDN", {0, 1}},
    {"PGA_TEST_MODE", {0, 1}}
};
};

#endif // AFE_HPP