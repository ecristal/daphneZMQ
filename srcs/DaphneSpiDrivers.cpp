#include "DaphneSpiDrivers.hpp"

CurrentMonitorDrivers::ADS1260::ADS1260():
    deviceAddress("/dev/spidev3.0"),
    deviceSpeed(1000000),
    spiMode(SPI_MODE_1),
    bitsPerWord(8),
    CRC8_TABLE(this->build_crc_table()),
    spi_ads1260(this->deviceAddress, this->deviceSpeed, this->spiMode, this->bitsPerWord){
        this->enableCRC();
        this->setDeviceFunction("DR", 0b01101); // data rate 14400 KSPS
        this->setDeviceFunction("FILTER", 0b100); // FILTER FIR
        this->setDeviceFunction("GAIN", 0b101); // data rate 14400 KSPS
    }

CurrentMonitorDrivers::ADS1260::~ADS1260(){}

std::array<uint8_t, 256> CurrentMonitorDrivers::ADS1260::build_crc_table(){
    
    uint8_t POLY = 0x07;
    std::array<uint8_t, 256> table{};
    for (int i = 0; i < 256; i++) {
        uint8_t crc = i;
        for (int j = 0; j < 8; j++) {
            if (crc & 0x80)
                crc = (crc << 1) ^ POLY;
            else
                crc <<= 1;
        }
        table[i] = crc;
    }
    return table;
}

uint8_t CurrentMonitorDrivers::ADS1260::ads1260_crc8_lut(const std::vector<uint8_t> &data) {
    uint8_t crc = 0xFF; // initial value per datasheet
    for (uint8_t byte : data) {
        crc = CRC8_TABLE[crc ^ byte];
    }
    return crc;
}

void CurrentMonitorDrivers::ADS1260::enableCRC(){
    uint8_t opCode = static_cast<uint8_t>(spiDevices_drivers_defines::ADS1260opCodes::WREG) | 0x5; //hardcode
    std::vector<uint8_t> tx_data = {opCode, 0b00100000};
    std::vector<uint8_t> rx_data = this->spi_ads1260.transfer(tx_data);
    if(rx_data[1] != opCode){
        throw std::runtime_error("ADS1260 enableCRC: The rx and tx opCodes do not match.");
    }
}

uint8_t CurrentMonitorDrivers::ADS1260::readRegister(const uint8_t &registerAddress){
    
    uint8_t opCode = static_cast<uint8_t>(spiDevices_drivers_defines::ADS1260opCodes::RREG) | registerAddress;
    std::vector<uint8_t> tx_data = {opCode, 0x00};
    uint8_t tx_crc = this->ads1260_crc8_lut(tx_data);
    tx_data.push_back(tx_crc);
    tx_data.push_back(0x00);
    tx_data.push_back(0x00);
    tx_data.push_back(0x00);
    std::vector<uint8_t> rx_data = this->spi_ads1260.transfer(tx_data);
    // Validate command CRC
    if (this->ads1260_crc8_lut({rx_data[1], rx_data[2]}) != rx_data[3]){
        throw std::runtime_error("ADS1260 read: command CRC mismatch.");
    }
    // Validate data CRC
    if (this->ads1260_crc8_lut({rx_data[4]}) != rx_data[5]){
        throw std::runtime_error("ADS1260 read: data CRC mismatch.");
    }
    if(rx_data[1] != opCode){
        throw std::runtime_error("ADS1260 read: The rx and tx opCodes do not match.");
    }
    return rx_data[4];
}

uint8_t CurrentMonitorDrivers::ADS1260::writeRegister(const uint8_t &registerAddress, const uint8_t &registerValue){
    
    uint8_t opCode = static_cast<uint8_t>(spiDevices_drivers_defines::ADS1260opCodes::WREG) | registerAddress;
    std::vector<uint8_t> tx_data = {opCode, registerValue};
    uint8_t tx_crc = this->ads1260_crc8_lut(tx_data);
    tx_data.push_back(tx_crc);
    tx_data.push_back(0x00);
    std::vector<uint8_t> rx_data = this->spi_ads1260.transfer(tx_data);
    if(this->ads1260_crc8_lut({rx_data[1], rx_data[2]}) != rx_data[3]){
        throw std::runtime_error("ADS1260 write: CRC mismatch.");
    }
    if(rx_data[1] != opCode){
        throw std::runtime_error("ADS1260 write: The rx and tx opCodes do not match.");
    }
    if(rx_data[2] != registerValue){
        throw std::runtime_error("ADS1260 write: The rx and tx values do not match.");
    }
    return rx_data[2];
}

uint8_t CurrentMonitorDrivers::ADS1260::setDeviceFunction(const std::string &functionName, const uint8_t &value){

    const auto ads1260_funct_it = spiDevices_drivers_defines::ADS1260FunctionDict.find(functionName);
	if (ads1260_funct_it == spiDevices_drivers_defines::ADS1260FunctionDict.end()) {
		throw std::invalid_argument("ADS1260 function name " + functionName + " not found in the dictionary.");
	}

    const spiDevices_drivers_defines::BitField& bit_field = ads1260_funct_it->second;
    const auto& registerAddr = bit_field.begin()->first;
	const auto& msb_pos = bit_field.begin()->second.first;
	const auto& lsb_pos = bit_field.begin()->second.second;
    uint8_t mask = ((1 << (msb_pos - lsb_pos + 1)) - 1) << lsb_pos;
    uint8_t registerValue = this->readRegister(registerAddr);
    registerValue = (registerValue & (~mask)); // Clear the bits
	registerValue |= ((value << lsb_pos) & mask); // Set the new value
    registerValue = this->writeRegister(registerAddr, registerValue);
    uint8_t checkValue = (registerValue & mask) >> lsb_pos;
    if(checkValue != value){
        throw std::invalid_argument("ADS1260: Written value different than read value.");
	}
    return checkValue;
}

uint8_t CurrentMonitorDrivers::ADS1260::getDeviceFunction(const std::string &functionName){

    const auto ads1260_funct_it = spiDevices_drivers_defines::ADS1260FunctionDict.find(functionName);
	if (ads1260_funct_it == spiDevices_drivers_defines::ADS1260FunctionDict.end()) {
		throw std::invalid_argument("ADS1260 function name " + functionName + " not found in the dictionary.");
	}

    const spiDevices_drivers_defines::BitField& bit_field = ads1260_funct_it->second;
    const auto& registerAddr = bit_field.begin()->first;
	const auto& msb_pos = bit_field.begin()->second.first;
	const auto& lsb_pos = bit_field.begin()->second.second;
    uint8_t mask = ((1 << (msb_pos - lsb_pos + 1)) - 1) << lsb_pos;
    uint8_t registerValue = this->readRegister(registerAddr);
    uint8_t checkValue = (registerValue & mask) >> lsb_pos;
    return checkValue;
}

CurrentMonitorDrivers::CurrentMonitor::CurrentMonitor():
    cm_adc(),
    fpgaReg(std::make_unique<FpgaReg>()){}

CurrentMonitorDrivers::CurrentMonitor::~CurrentMonitor(){}