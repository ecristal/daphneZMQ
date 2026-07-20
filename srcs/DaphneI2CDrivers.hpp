#ifndef DaphneI2CDrivers_HPP
#define DaphneI2CDrivers_HPP

#include <array>
#include <thread>
#include <chrono>
#include <functional>
#include <memory>
#include <mutex>
#include <sstream>
#include <iomanip>


#include "defines.hpp"
#include "I2CDevice.hpp"

namespace I2CMezzDrivers{
    class HDMezzDriver {
    public:
        struct PowerRequests {
            bool power5V;
            bool power3V3; // Kept for protocol compatibility; the schematic names this rail CE.
            uint8_t outputPort;
        };

        using DeviceFactory = std::function<std::unique_ptr<I2CRegisterDevice>(const std::string&, uint8_t)>;
        using DelayFunction = std::function<void(std::chrono::milliseconds)>;

        HDMezzDriver();
        HDMezzDriver(std::string devicePath, DeviceFactory deviceFactory, DelayFunction delayFunction);
        ~HDMezzDriver() = default;

        HDMezzDriver(const HDMezzDriver&) = delete;
        HDMezzDriver& operator=(const HDMezzDriver&) = delete;

        void enableAfeBlock(uint8_t afeBlock, bool enable);
        bool isAfeBlockEnabled(uint8_t afeBlock) const;
        bool isAfeBlockConfigured(uint8_t afeBlock) const;
        void probeAfeBlock(uint8_t afeBlock);
        void setRShunt(uint8_t afeBlock, double rShunt, const std::string &rail);
        void setMaxCurrentScale(uint8_t afeBlock, double maxCurrent, const std::string &rail);
        void setMaxCurrentShutdown(uint8_t afeBlock, double maxCurrent, const std::string &rail);
        double getRShunt(uint8_t afeBlock, const std::string &rail) const;
        double getMaxCurrentScale(uint8_t afeBlock, const std::string &rail) const;
        double getMaxCurrentShutdown(uint8_t afeBlock, const std::string &rail) const;
        double getMaxPower(uint8_t afeBlock, const std::string &rail) const;
        double getCurrentLsb(uint8_t afeBlock, const std::string &rail) const;
        uint16_t getShuntCal(uint8_t afeBlock, const std::string &rail) const;

        struct BlockConfiguration { double rShunt5V, rShunt3V3, maxCurrentScale5V, maxCurrentScale3V3, maxCurrentShutdown5V, maxCurrentShutdown3V3; };
        void configureHdMezzAfeBlock(uint8_t afeBlock);
        void configureHdMezzAfeBlock(uint8_t afeBlock, const BlockConfiguration& configuration);
        void setPowerRequests(uint8_t afeBlock, bool power5V, bool power3V3);
        PowerRequests readPowerRequests(uint8_t afeBlock);
        void powerOn_HDMezzAfeBlock(uint8_t afeBlock, bool powerOn, const std::string &rail);
        bool isPowerOn(uint8_t afeBlock, const std::string &rail);

        double readRailVoltage(uint8_t afeBlock, const std::string &rail);
        double readRailCurrent(uint8_t afeBlock, const std::string &rail);
        double readRailPower(uint8_t afeBlock, const std::string &rail);
        bool checkAlertStatus(uint8_t afeBlock, const std::string &rail);
        

    private:

        struct RailCalibration {
            double currentLsb;
            uint16_t shuntCal;
            double maxPower;
            uint16_t alertLimit;
        };

        std::string device_path_;
        DeviceFactory device_factory_;
        DelayFunction delay_;
        std::unique_ptr<I2CRegisterDevice> mux_;
        std::unique_ptr<I2CRegisterDevice> ina_5V_;
        std::unique_ptr<I2CRegisterDevice> ina_3V3_;
        std::unique_ptr<I2CRegisterDevice> tca9536_;
        mutable std::mutex mutex_;

        std::vector<double> r_shunt_5V = {36e-3, 36e-3, 36e-3, 36e-3, 36e-3}; // Ohm
        std::vector<double> r_shunt_3V3 = {0.3, 0.3, 0.3, 0.3, 0.3}; // Ohm
        std::vector<double> max_current_5V_scale = {200e-3, 200e-3, 200e-3, 200e-3, 200e-3}; // Ampere. This sets the maximun current that can be measured
        std::vector<double> max_current_3V3_scale = {200e-3, 200e-3, 200e-3, 200e-3, 200e-3}; // Ampere. This sets the maximun current that can be measured
        std::vector<double> max_current_5V_shutdown = {120e-3, 120e-3, 120e-3, 120e-3, 120e-3}; // Ampere. This sets the maximun current before an alert conditions is triggered
        std::vector<double> max_current_3V3_shutdown = {10e-3, 10e-3, 10e-3, 10e-3, 10e-3}; // Ampere. This sets the maximun current before an alert conditions is triggered
        std::vector<double> max_power_5V = {0.0, 0.0, 0.0, 0.0, 0.0}; // Watt. This sets the maximun power before an alert conditions is triggered
        std::vector<double> max_power_3V3 = {0.0, 0.0, 0.0, 0.0, 0.0}; // Watt. This sets the maximun power before an alert conditions is triggered
        std::vector<double> current_lsb_5V = {0.0, 0.0, 0.0, 0.0, 0.0};
        std::vector<double> current_lsb_3V3 = {0.0, 0.0, 0.0, 0.0, 0.0};
        std::vector<uint16_t> shunt_cal_5V = {0, 0, 0, 0, 0};
        std::vector<uint16_t> shunt_cal_3V3 = {0, 0, 0, 0, 0};
        std::vector<uint16_t> alert_limit_5V = {0, 0, 0, 0, 0};
        std::vector<uint16_t> alert_limit_3V3 = {0, 0, 0, 0, 0};
        
        std::vector<bool> enabled_afeBlocks = {false, false, false, false, false}; // to keep track of which AFE blocks are populated with HDMezz's
        std::vector<bool> configured_afeBlocks = {false, false, false, false, false};

        static void validateAfeBlock(uint8_t afeBlock);
        static void validateRail(const std::string &rail);
        static RailCalibration calculateRailCalibration(double rShunt, double maxCurrentScale,
                                                         double maxCurrentShutdown, double nominalVoltage);
        void configureCalibrationValuesUnlocked();
        void configureHdMezzAfeBlockUnlocked(uint8_t afeBlock);
        void requireEnabledUnlocked(uint8_t afeBlock) const;
        void requireConfiguredUnlocked(uint8_t afeBlock) const;
        void probeAfeBlockUnlocked(uint8_t afeBlock);
        void initializeTcaSafeUnlocked(uint8_t afeBlock);

        I2CRegisterDevice& inaDeviceUnlocked(uint8_t deviceAddress);
        uint16_t readINA232RegisterUnlocked(uint8_t afeBlock, uint8_t deviceAddress, uint8_t registerAddress);
        uint16_t readINA232FunctionUnlocked(uint8_t afeBlock, uint8_t deviceAddress, const std::string &functionName);
        void writeINA232RegisterVerifiedUnlocked(uint8_t afeBlock, uint8_t deviceAddress,
                                                  uint8_t registerAddress, uint16_t value,
                                                  uint16_t verificationMask = 0xFFFF);
        void writeINA232FunctionUnlocked(uint8_t afeBlock, uint8_t deviceAddress,
                                         const std::string &functionName, uint16_t value);

        uint8_t readTCA9536RegisterUnlocked(uint8_t afeBlock, uint8_t registerAddress);
        void writeTCA9536RegisterVerifiedUnlocked(uint8_t afeBlock, uint8_t registerAddress,
                                                   uint8_t value, uint8_t verificationMask = 0xFF);
        PowerRequests readPowerRequestsUnlocked(uint8_t afeBlock);
        void setPowerRequestsUnlocked(uint8_t afeBlock, bool power5V, bool power3V3);
        
        void selectAfeBlockUnlocked(uint8_t afeBlock);

    };
}

namespace I2CRegulatorsDrivers{
    class PJT004A0X43_SRZ_Driver
    {
    public:
        PJT004A0X43_SRZ_Driver();
        ~PJT004A0X43_SRZ_Driver();

        // Let's implement these readout functions for now.
        // Very risky to implement write functions.
        double readRailVoltage(const uint8_t &regulatorNumber);
        double readRailCurrent(const uint8_t &regulatorNumber);
        double readTemperature(const uint8_t &regulatorNumber);

    private:

        I2CDevice REG_3VD3;
        I2CDevice REG_2VA1;
        I2CDevice REG_3VA6;
        I2CDevice REG_1VD8;
        double decodeRaw(const uint16_t &rawData, const uint16_t &exponentLSBPos, const uint16_t &mantissaMSBPos);
        double decodeRaw(const uint16_t &rawData, const int &exponent);
    };
}

namespace I2CADCsDrivers{
    class ADS7138_Driver
    // For now, this class implements the bare minimum to do an Acquisition of the enabled channels.
    {
    public:
        ADS7138_Driver(const uint8_t &deviceAddress);
        ~ADS7138_Driver();

        uint8_t getDeviceAddress();
        void setDeviceAddress();

        void resetDevice();
        void configureDevice();
        void calibrateOffsetError();
        void setEnabledChannels(const std::vector<bool> &enabled_channels);
        std::vector<bool> getEnabledChannels() const;
        void writeSingleRegister(const uint8_t &registerAddress, const uint8_t &value);
        uint8_t readSingleRegister(const uint8_t &registerAddress);
        std::vector<double> readData(const uint8_t &numSamples);

    private:

        I2CDevice ADC_ADS7138;

        uint8_t deviceAddress;
        std::string operationMode = "Auto-Sequence"; // For now the only opmode is Auto-Sequence.
        std::vector<bool> enabled_channels = {false, false, false, false,
                                              false, false, false, false};
        uint8_t getChannelsListByte(const std::vector<bool> &channels);
    };
}
#endif // DaphneI2CDrivers_HPP
