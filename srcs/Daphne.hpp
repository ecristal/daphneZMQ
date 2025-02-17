#ifndef DAPHNE_HPP
#define DAPHNE_HPP

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
#include <map>
#include <tuple>
#include <vector>
#include <algorithm>
#include <functional>
#include <cmath>
#include <optional>

#include "Afe.hpp"
#include "Dac.hpp"
#include "FrontEnd.hpp"
#include "SpyBuffer.hpp"

class Daphne {
public:
    // Constructor

    Daphne();

    // Destructor
    ~Daphne();

    Afe* getAfe();
    Dac* getDac();
    FrontEnd* getFrontEnd();
    SpyBuffer* getSpyBuffer();

    std::optional<std::pair<uint32_t, uint32_t>> longestIdenticalSubsequenceIndices(const std::vector<uint32_t>& nums);
    std::vector<uint32_t> scanGeneric(const uint32_t& afe,const std::string& what,const uint32_t& taps, std::function<uint32_t(const uint32_t&, const uint32_t&)> setFunc);
    uint32_t setBestDelay(const uint32_t& afe, const size_t& delayTaps = 512);
    uint32_t setBestBitslip(const uint32_t& afe, const size_t& bitslipTaps = 16);
    double calcInputVoltage(const double& value, const double& vGain_mV);

private:
    std::unique_ptr<Afe> afe;
    std::unique_ptr<Dac> dac;
    std::unique_ptr<FrontEnd> frontend;
    std::unique_ptr<SpyBuffer> spyBuffer;

    std::unordered_map<std::string, std::vector<double>> AFE_GAIN_LUT = {
        {"VCNTL",{0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5}},
        {"GAIN" ,{36.45, 33.91, 30.78, 27.39, 23.74, 20.69, 17.11, 13.54, 10.27, 6.48, 3.16, -0.35, -2.48, -3.58, -4.01, -4}}
    };

    template <typename T>
    int findIndex(const std::vector<T>& data, const T& target);
};

#endif // DAPHNE_HPP