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
#include "defines.hpp"

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
    const std::unordered_map<std::string, Afe::BitField> afeFunctionDict = afe_definitions::afeFunctionDict;
    const std::unordered_map<std::string, std::vector<uint16_t>> afeFunctionAvailableOptionsDict = afe_definitions::afeFunctionAvailableOptionsDict;
};

#endif // AFE_HPP