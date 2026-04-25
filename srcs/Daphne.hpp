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
#include <mutex>
#include <tuple>
#include <vector>
#include <algorithm>
#include <functional>
#include <cmath>
#include <optional>
#include <atomic>

#include "Afe.hpp"
#include "Dac.hpp"
#include "FrontEnd.hpp"
#include "SpyBuffer.hpp"
#include "DaphneI2CDrivers.hpp"
#include "DaphneSpiDrivers.hpp"

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
    I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver* getRegulatorsDriver();
    I2CADCsDrivers::ADS7138_Driver* getADS7138_Driver_addr_0x10();
    I2CADCsDrivers::ADS7138_Driver* getADS7138_Driver_addr_0x17();
    CurrentMonitorDrivers::CurrentMonitor* getCurrentMonitorDriver();

    std::optional<std::pair<uint32_t, uint32_t>> longestIdenticalSubsequenceIndices(const std::vector<uint32_t>& nums);
    std::vector<uint32_t> scanGeneric(const uint32_t& afe,const std::string& what,const uint32_t& taps, std::function<uint32_t(const uint32_t&, const uint32_t&)> setFunc);
    uint32_t setBestDelay(const uint32_t& afe, const size_t& delayTaps = 512, std::string* debug_out = nullptr);
    uint32_t setBestBitslip(const uint32_t& afe, const size_t& bitslipTaps = 16, std::string* debug_out = nullptr, bool* matched_out = nullptr);
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
    void setBiasControlDictValue(const uint32_t& biasControl);
    uint32_t getBiasControlDictValue();

    //Atomic variable to share between threads
    std::atomic<bool> isI2C_1_device_configuring;
    std::atomic<bool> isI2C_2_device_configuring;
    std::mutex i2c_2_mutex;
    std::atomic<bool> user_vbias_voltage_request;
    std::atomic<bool> is_vbias_voltage_monitor_reading;
    //Atomic monitor voltages and currents
    std::array<std::atomic<bool>, 5> HDMezz_5V_is_powered{false, false, false, false, false};
    std::array<std::atomic<bool>, 5> HDMezz_3V3_is_powered{false, false, false, false, false};
    std::array<std::atomic<double>, 5> HDMezz_5V_voltage{0.0, 0.0, 0.0, 0.0, 0.0};
    std::array<std::atomic<double>, 5> HDMezz_5V_current{0.0, 0.0, 0.0, 0.0, 0.0};
    std::array<std::atomic<double>, 5> HDMezz_3V3_voltage{0.0, 0.0, 0.0, 0.0, 0.0};
    std::array<std::atomic<double>, 5> HDMezz_3V3_current{0.0, 0.0, 0.0, 0.0, 0.0};
    std::array<std::atomic<double>, 5> HDMezz_5V_power{0.0, 0.0, 0.0, 0.0, 0.0};
    std::array<std::atomic<double>, 5> HDMezz_3V3_power{0.0, 0.0, 0.0, 0.0, 0.0};
    std::array<std::atomic<bool>, 5>   HDMezz_5V_alert{false, false, false, false, false};
    std::array<std::atomic<bool>, 5>   HDMezz_3V3_alert{false, false, false, false, false};

    std::atomic<double> _1V8A_voltage;
    std::atomic<double> _3V3A_voltage;
    std::atomic<double> _n5VA_voltage;

    std::atomic<double> _3V3PDS_voltage;
    std::atomic<double> _1V8PDS_voltage;
    std::atomic<double> _VBIAS_0_voltage;
    std::atomic<double> _VBIAS_1_voltage;
    std::atomic<double> _VBIAS_2_voltage;
    std::atomic<double> _VBIAS_3_voltage;
    std::atomic<double> _VBIAS_4_voltage;

private:
    std::unique_ptr<Afe> afe;
    std::unique_ptr<Dac> dac;
    std::unique_ptr<FrontEnd> frontend;
    std::unique_ptr<SpyBuffer> spyBuffer;
    std::unique_ptr<I2CMezzDrivers::HDMezzDriver> hdmezzdriver;
    std::unique_ptr<I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver> regulatorsdriver;
    std::unique_ptr<I2CADCsDrivers::ADS7138_Driver> ads7138driver_addr_0x10;
    std::unique_ptr<I2CADCsDrivers::ADS7138_Driver> ads7138driver_addr_0x17;
    std::unique_ptr<CurrentMonitorDrivers::CurrentMonitor> current_monitor;

    std::unordered_map<std::string, std::vector<double>> AFE_GAIN_LUT = {
        {"VCNTL",{0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5}},
        {"GAIN" ,{36.45, 33.91, 30.78, 27.39, 23.74, 20.69, 17.11, 13.54, 10.27, 6.48, 3.16, -0.35, -2.48, -3.58, -4.01, -4}}
    };

    struct StateKey {
        enum class Kind : uint8_t {
            kAfeReg = 1,
            kAfeAttenuation = 2,
            kChannelOffset = 3,
            kChannelTrim = 4,
            kBiasVoltage = 5,
            kBiasControl = 6,
        };

        Kind kind{};
        uint32_t a = 0;
        uint32_t b = 0;

        bool operator==(const StateKey& other) const noexcept {
            return kind == other.kind && a == other.a && b == other.b;
        }
    };

    struct StateKeyHash {
        size_t operator()(const StateKey& k) const noexcept {
            uint64_t x = (static_cast<uint64_t>(k.a) << 32) ^ static_cast<uint64_t>(k.b);
            x ^= (static_cast<uint64_t>(k.kind) << 56);
            x ^= x >> 33;
            x *= 0xff51afd7ed558ccdULL;
            x ^= x >> 33;
            x *= 0xc4ceb9fe1a85ec53ULL;
            x ^= x >> 33;
            return static_cast<size_t>(x);
        }
    };

    mutable std::mutex state_mutex_;
    std::unordered_map<StateKey, uint32_t, StateKeyHash> state_;

    template <typename T>
    int findIndex(const std::vector<T>& data, const T& target);
    void initRegDictHistory();
};

#endif // DAPHNE_HPP
