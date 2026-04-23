#ifndef DaphneI2CDrivers_HPP
#define DaphneI2CDrivers_HPP

#include <thread>
#include <chrono>

#include "defines.hpp"
#include "I2CDevice.hpp"

namespace I2CMezzDrivers{
    class HDMezzDriver {
    public:
        HDMezzDriver();
        ~HDMezzDriver();

        void enableAfeBlock(const uint8_t &afeBlock, const bool &enable);
        bool isAfeBlockEnabled(const uint8_t &afeBlock);
        void setRShunt(const uint8_t &afeBlock, const double &rShunt, const std::string &rail);
        void setMaxCurrentScale(const uint8_t &afeBlock, const double &maxCurrent, const std::string &rail);
        void setMaxCurrentShutdown(const uint8_t &afeBlock, const double &maxCurrent, const std::string &rail);
        double getRShunt(const uint8_t &afeBlock, const std::string &rail);
        double getMaxCurrentScale(const uint8_t &afeBlock, const std::string &rail);
        double getMaxCurrentShutdown(const uint8_t &afeBlock, const std::string &rail);
        double getMaxPower(const uint8_t &afeBlock, const std::string &rail);
        double getCurrentLsb(const uint8_t &afeBlock, const std::string &rail);
        uint16_t getShuntCal(const uint8_t &afeBlock, const std::string &rail);

        void configureHdMezzAfeBlock(const uint8_t &afeBlock);
        void powerOn_HDMezzAfeBlock(const uint8_t &afeBlock, const bool &powerOn, const std::string &rail);

        double readRailVoltage(const uint8_t &afeBlock, const std::string &rail);
        double readRailCurrent(const uint8_t &afeBlock, const std::string &rail);
        double readRailPower(const uint8_t &afeBlock, const std::string &rail);

    private:

        I2CDevice I2C_exp_mezz; // Get the adress from defines.hpp
        
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
        
        std::vector<bool> enabled_afeBlocks = {false, false, false, false, false}; // to keep track of which AFE blocks are populated with HDMezz's

        uint16_t enable_alert_flags = 0b0000100000000001;

        void configureCalibrationValues();
        uint16_t readINA232Register(const uint8_t &afeBlock, const uint8_t &deviceAddress, const uint8_t &registerAddress);
        void writeINA232Register(const uint8_t &afeBlock, const uint8_t &deviceAddress, const uint8_t &registerAddress, const uint16_t &value);
        uint16_t readTCA9536Register(const uint8_t &afeBlock, const uint8_t &registerAddress);
        void writeTCA9536Register(const uint8_t &afeBlock, const uint8_t &registerAddress, const uint8_t &value);
        void selectAfeBlock(const uint8_t &afeBlock);

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