#ifndef SPI_HPP
#define SPI_HPP

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

class Spi {
public:
    // Constructor
    Spi();

    // Destructor
    ~Spi();

    bool isBusy();
    bool waitNotBusy(const double& timeout = 0.01);
    uint32_t setData(const std::string& regName, const uint32_t& value);
    uint32_t getData(const std::string& regName);
    FpgaReg* getFpgaReg();
    
private:
    std::unique_ptr<FpgaReg> fpgaReg;
};

#endif // SPI_HPP