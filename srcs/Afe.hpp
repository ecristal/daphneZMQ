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

#include "Spi.hpp"

class Afe {
public:
    // Constructor
    Afe();

    // Destructor
    ~Afe();
    
    uint32_t setReset(const uint32_t& reset);
    uint32_t doReset();
    uint32_t setPowerdown(const uint32_t& powerdown);
    uint32_t getPowerdown();
    uint32_t setRegister(const uint32_t& afe, const uint32_t& register_, const uint32_t& value);
    uint32_t getRegister(const uint32_t& afe, const uint32_t& register_);
    uint32_t initAFE(const uint32_t& afe, const std::unordered_map<uint32_t, uint32_t> &regDict);

private:
    std::unique_ptr<Spi> spi;
};

#endif // AFE_HPP