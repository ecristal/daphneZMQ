#ifndef FPGAREG_HPP
#define FPGAREG_HPP

#include <cstdint>
#include <string>
#include <vector>
#include <stdexcept>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <tuple>
#include <memory>

#include "FpgaRegDict.hpp"
#include "reg.hpp"

class FpgaReg {
public:
    // Constructor
    FpgaReg();

    // Destructor
    ~FpgaReg();

    uint32_t setBits(const std::string &regName, const std::string &bitName, const uint32_t &Data);
    uint32_t getBits(const std::string &regName, const std::string &bitName, const uint32_t &offset = 0);
    const uint32_t* getRegisterPointer(const std::string &regName, const std::string &bitName, const uint32_t &offset);
    uint32_t getBitsFast(const uint32_t &offset = 0, const bool& bitEndianess = false);
    void getRegisterAndCacheData(const std::string &regName);
    
private:
    FpgaRegDict fpgaRegDict;
    uint64_t baseAddr;
    size_t memLen;
    std::unique_ptr<reg> fpgaMem;
};

#endif // FPGAREG_HPP