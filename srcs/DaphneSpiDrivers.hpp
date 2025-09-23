#ifndef DAPHNESPIDRIVERS_HPP
#define DAPHNESPIDRIVERS_HPP

#include "SpiDevice.hpp"
#include "FpgaReg.hpp"
#include "defines.hpp"

namespace CurrentMonitorDrivers{
    class ADS1260{
        public:
            ADS1260();
            ~ADS1260();

            void resetDevice(const bool &);
            void enableCRC(); //important to have readback
            uint8_t readRegister(const uint8_t &registerAddress);
            uint8_t writeRegister(const uint8_t &registerAddress, const uint8_t &registerValue);
            uint8_t setDeviceFunction(const std::string &functionName, const uint8_t &value);
            uint8_t getDeviceFunction(const std::string &functionName);
            double getData(const uint8_t &channel);

        private:

            std::string deviceAddress;
            uint32_t deviceSpeed;
            uint8_t spiMode;
            uint8_t bitsPerWord;
            
            std::array<uint8_t, 256> build_crc_table();
            uint8_t ads1260_crc8_lut(const std::vector<uint8_t>& data);
            const std::array<uint8_t, 256> CRC8_TABLE;

            SpiDevice spi_ads1260;
    };

    class CurrentMonitor{
        public:
            CurrentMonitor();
            ~CurrentMonitor();

            void setSelectedCMReaoutChannel(const uint16_t &channel){};
            uint16_t getSelectedCMReadoutChannel(){return 0;};
            double readSelectedCMChannel(const uint16_t &channel){return 0.0;};
            
        private:
            ADS1260 cm_adc;
            std::unique_ptr<FpgaReg> fpgaReg;

            uint16_t selected_channel;
    };
};

#endif