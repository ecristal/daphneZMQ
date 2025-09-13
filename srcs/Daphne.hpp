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
#include "DaphneI2CDrivers.hpp"

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
    I2CMezzDrivers::HDMezzDriver* getHDMezzDriver();
    I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver* getRegulatorsDriver();

    std::optional<std::pair<uint32_t, uint32_t>> longestIdenticalSubsequenceIndices(const std::vector<uint32_t>& nums);
    std::vector<uint32_t> scanGeneric(const uint32_t& afe,const std::string& what,const uint32_t& taps, std::function<uint32_t(const uint32_t&, const uint32_t&)> setFunc);
    uint32_t setBestDelay(const uint32_t& afe, const size_t& delayTaps = 512);
    uint32_t setBestBitslip(const uint32_t& afe, const size_t& bitslipTaps = 16);
    double calcInputVoltage(const double& value, const double& vGain_mV);
    
    void setAfeRegDictValue(const uint32_t& afe, const uint32_t &regAddr, const uint32_t &regValue);
    uint32_t getAfeRegDictValue(const uint32_t& afe, const uint32_t &regAddr);
    void setAfeAttenuationDictValue(const uint32_t& afe, const uint32_t &attenuation);
    uint32_t getAfeAttenuationDictValue(const uint32_t& afe);
    void setChOffsetDictValue(const uint32_t &ch, const uint32_t &offset);
    uint32_t getChOffsetDictValue(const uint32_t &ch);
    void setChTrimDictValue(const uint32_t &ch, const uint32_t &trim);
    uint32_t getChTrimDictValue(const uint32_t &ch);
    void setBiasVoltageDictValue(const uint32_t& afe, const uint32_t& biasVoltage);
    uint32_t getBiasVoltageDictValue(const uint32_t& afe);
    void setBiasControlDictValue(const uint32_t& biasControl) {this->biasControlSetting = biasControl;}
    uint32_t getBiasControlDictValue() {return this->biasControlSetting;}

private:
    std::unique_ptr<Afe> afe;
    std::unique_ptr<Dac> dac;
    std::unique_ptr<FrontEnd> frontend;
    std::unique_ptr<SpyBuffer> spyBuffer;
    std::unique_ptr<I2CMezzDrivers::HDMezzDriver> hdmezzdriver;
    std::unique_ptr<I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver> regulatorsdriver;

    std::unordered_map<std::string, std::vector<double>> AFE_GAIN_LUT = {
        {"VCNTL",{0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5}},
        {"GAIN" ,{36.45, 33.91, 30.78, 27.39, 23.74, 20.69, 17.11, 13.54, 10.27, 6.48, 3.16, -0.35, -2.48, -3.58, -4.01, -4}}
    };

    std::vector<std::unordered_map<uint32_t, uint32_t>> afeRegDictSetting;
    std::unordered_map<uint32_t, uint32_t> afeAttenuationDictSetting;
    std::unordered_map<uint32_t, uint32_t> chOffsetDictSetting;
    std::unordered_map<uint32_t, uint32_t> chTrimDictSetting;
    std::unordered_map<uint32_t, uint32_t> biasVoltageSetting;
    uint32_t biasControlSetting;

    template <typename T>
    int findIndex(const std::vector<T>& data, const T& target);
    void initRegDictHistory();
};

#endif // DAPHNE_HPP