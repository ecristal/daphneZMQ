#ifndef DaphneI2CDrivers_HPP
#define DaphneI2CDrivers_HPP

#include "defines.hpp"
#include "I2CDevice.hpp"

namespace I2CMezzDrivers{
    class HDMezzDriver {
    public:
        HDMezzDriver();
        ~HDMezzDriver();

        void enableAfeBlock(const uint8_t &afeBlock, const bool &enable);
        bool isAfeBlockEnabled(const uint8_t &afeBlock);
        void setRShunt5V(const uint8_t &afeBlock, const double &rShunt);
        void setRShunt3V3(const uint8_t &afeBlock, const double &rShunt);
        void setMaxCurrent5VScale(const uint8_t &afeBlock, const double &maxCurrent);
        void setMaxCurrent3V3Scale(const uint8_t &afeBlock, const double &maxCurrent);
        void setMaxCurrent5VShutdown(const uint8_t &afeBlock, const double &maxCurrent);
        void setMaxCurrent3V3Shutdown(const uint8_t &afeBlock, const double &maxCurrent);
        double getRShunt5V(const uint8_t &afeBlock);
        double getRShunt3V3(const uint8_t &afeBlock);
        double getMaxCurrent5VScale(const uint8_t &afeBlock);
        double getMaxCurrent3V3Scale(const uint8_t &afeBlock);
        double getMaxCurrent5VShutdown(const uint8_t &afeBlock);
        double getMaxCurrent3V3Shutdown(const uint8_t &afeBlock);
        double getMaxPower5V(const uint8_t &afeBlock);
        double getMaxPower3V3(const uint8_t &afeBlock);
        double getCurrentLsb5V(const uint8_t &afeBlock);
        double getCurrentLsb3V3(const uint8_t &afeBlock);
        uint16_t getShuntCal5V(const uint8_t &afeBlock);
        uint16_t getShuntCal3V3(const uint8_t &afeBlock);

        void configureHdMezzAfeBlock(const uint8_t &afeBlock);
        void powerOn_5V_HDMezzAfeBlock(const uint8_t &afeBlock, const bool &powerOn);
        void powerOn_3V3_HDMezzAfeBlock(const uint8_t &afeBlock, const bool &powerOn);

        double readRailVoltage5V(const uint8_t &afeBlock);
        double readRailVoltage3V3(const uint8_t &afeBlock);
        double readRailCurrent5V(const uint8_t &afeBlock);
        double readRailCurrent3V3(const uint8_t &afeBlock);
        double readRailPower5V(const uint8_t &afeBlock);
        double readRailPower3V3(const uint8_t &afeBlock);

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

    };
}

namespace I2CRegulartorsDrivers{
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
#endif // DaphneI2CDrivers_HPP