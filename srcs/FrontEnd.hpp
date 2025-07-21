#ifndef FRONTEND_HPP
#define FRONTEND_HPP

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

class FrontEnd {
public:
    // Constructor
    FrontEnd();

    // Destructor
    ~FrontEnd();
    
    uint32_t doResetDelayCtrl();
    uint32_t doResetSerDesCtrl();
    uint32_t setEnableDelayVtc(const uint32_t& value);
    uint32_t getEnableDelayVtc();
    uint32_t getDelayCtrlReady();
    uint32_t doTrigger();
    uint32_t setDelay(const uint8_t& afe,const uint32_t& delay);
    uint32_t getDelay(const uint8_t& afe);
    uint32_t setBitslip(const uint8_t& afe,const uint32_t& bitslip);
    uint32_t getBitslip(const uint8_t& afe);
    uint32_t resetDelayCtrlValues();

private:
    std::unique_ptr<FpgaReg> fpgaReg;
};

#endif // FRONTEND_HPP