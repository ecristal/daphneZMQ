#include "DaphneI2CDrivers.hpp"

#include <cmath>

I2CMezzDrivers::HDMezzDriver::HDMezzDriver():
    I2C_exp_mezz("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("I2C_EXP_MEZZ")){
    configureCalibrationValues();
}

I2CMezzDrivers::HDMezzDriver::~HDMezzDriver() {}

void I2CMezzDrivers::HDMezzDriver::configureCalibrationValues(){
    int numberOfAfes = 5;
    for(int afeBlock = 0; afeBlock < numberOfAfes; afeBlock++){
        this->current_lsb_5V[afeBlock] = this->max_current_5V_scale[afeBlock] / ((double)std::pow(2,15));
        this->current_lsb_3V3[afeBlock] = this->max_current_3V3_scale[afeBlock] / ((double)std::pow(2,15));
        this->shunt_cal_5V[afeBlock] = (uint16_t)(0.00512 / (this->current_lsb_5V[afeBlock] * this->r_shunt_5V[afeBlock]));
        this->shunt_cal_3V3[afeBlock] = (uint16_t)(0.00512 / (this->current_lsb_3V3[afeBlock] * this->r_shunt_3V3[afeBlock]));
        this->max_power_5V[afeBlock] = this->max_current_5V_shutdown[afeBlock] * 5.0;
        this->max_power_3V3[afeBlock] = this->max_current_3V3_shutdown[afeBlock] * 3.3;
    }
}

void I2CMezzDrivers::HDMezzDriver::enableAfeBlock(const uint8_t &afeBlock, const bool &enable){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    this->enabled_afeBlocks[afeBlock] = enable;
}

bool I2CMezzDrivers::HDMezzDriver::isAfeBlockEnabled(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->enabled_afeBlocks[afeBlock];
}

void I2CMezzDrivers::HDMezzDriver::setRShunt(const uint8_t &afeBlock, const double &rShunt, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rShunt <= 0){
        throw std::invalid_argument("Invalid Rshunt value. It must be greater than zero.");
    }
    if(rail == "5V"){
        this->r_shunt_5V[afeBlock] = rShunt;
    }
    else if(rail == "3V3"){
        this->r_shunt_3V3[afeBlock] = rShunt;
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
    configureCalibrationValues();
}

void I2CMezzDrivers::HDMezzDriver::setMaxCurrentScale(const uint8_t &afeBlock, const double &maxCurrent, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(maxCurrent <= 0){
        throw std::invalid_argument("Invalid Max Current Scale value. It must be greater than zero.");
    }
    if(rail == "5V"){
        this->max_current_5V_scale[afeBlock] = maxCurrent;
    }
    else if(rail == "3V3"){
        this->max_current_3V3_scale[afeBlock] = maxCurrent;
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
    configureCalibrationValues();
}

void I2CMezzDrivers::HDMezzDriver::setMaxCurrentShutdown(const uint8_t &afeBlock, const double &maxCurrent, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(maxCurrent <= 0){
        throw std::invalid_argument("Invalid Max Current Shutdown value. It must be greater than zero.");
    }
    if(rail == "5V"){
        this->max_current_5V_shutdown[afeBlock] = maxCurrent;
    }
    else if(rail == "3V3"){
        this->max_current_3V3_shutdown[afeBlock] = maxCurrent;
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
    configureCalibrationValues();
}

double I2CMezzDrivers::HDMezzDriver::getRShunt(const uint8_t &afeBlock, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rail == "5V"){
        return this->r_shunt_5V[afeBlock];
    }
    else if(rail == "3V3"){
        return this->r_shunt_3V3[afeBlock];
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
}

double I2CMezzDrivers::HDMezzDriver::getMaxCurrentScale(const uint8_t &afeBlock, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rail == "5V"){
        return this->max_current_5V_scale[afeBlock];
    }
    else if(rail == "3V3"){
        return this->max_current_3V3_scale[afeBlock];
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
}

double I2CMezzDrivers::HDMezzDriver::getMaxCurrentShutdown(const uint8_t &afeBlock, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rail == "5V"){
        return this->max_current_5V_shutdown[afeBlock];
    }
    else if(rail == "3V3"){
        return this->max_current_3V3_shutdown[afeBlock];
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
}

double I2CMezzDrivers::HDMezzDriver::getMaxPower(const uint8_t &afeBlock, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rail == "5V"){
        return this->max_power_5V[afeBlock];
    }
    else if(rail == "3V3"){
        return this->max_power_3V3[afeBlock];
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
}

double I2CMezzDrivers::HDMezzDriver::getCurrentLsb(const uint8_t &afeBlock, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rail == "5V"){
        return this->current_lsb_5V[afeBlock];
    }
    else if(rail == "3V3"){
        return this->current_lsb_3V3[afeBlock];
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
}

uint16_t I2CMezzDrivers::HDMezzDriver::getShuntCal(const uint8_t &afeBlock, const std::string &rail){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rail == "5V"){
        return this->shunt_cal_5V[afeBlock];
    }
    else if(rail == "3V3"){
        return this->shunt_cal_3V3[afeBlock];
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
}

void I2CMezzDrivers::HDMezzDriver::configureHdMezzAfeBlock(const uint8_t &afeBlock){

    this->writeINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"), "SHUNT_CAL", this->shunt_cal_5V[afeBlock]);

    uint16_t max_power_5V_reg = (uint16_t)(this->max_power_5V[afeBlock] / (32*this->current_lsb_5V[afeBlock]));
    this->writeINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"), "LIMIT", max_power_5V_reg);
    
    this->writeINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"), "LEN", 0x1);
    this->writeINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"), "POL", 0x1);

    this->writeINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"), "SHUNT_CAL", this->shunt_cal_3V3[afeBlock]);

    uint16_t max_power_3V3_reg = (uint16_t)(this->max_power_3V3[afeBlock] / (32*this->current_lsb_3V3[afeBlock]));
    this->writeINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"), "LIMIT", max_power_3V3_reg);

    this->writeINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"), "LEN", 0x1);
    this->writeINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"), "POL", 0x1);

    this->writeTCA9536Register(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_CONF_REG"), 0xF0); // Set all pins as outputs

}

void I2CMezzDrivers::HDMezzDriver::powerOn_HDMezzAfeBlock(const uint8_t &afeBlock, const bool &powerOn, const std::string &rail){
    uint8_t output_port;
    output_port = this->readTCA9536Register(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG"));
    if(rail == "5V"){
        if(powerOn){ 
            output_port |= 0b00000001; // Set bit 0 to 1 to power on the 5V
        } else {
            output_port &= 0b11111110; // Set bit 0 to 0 to power off the 5V
        }
    } else if(rail == "3V3"){
        if(powerOn){ 
            output_port |= 0b00000010; // Set bit 1 to 1 to power on the 3.3V
        } else {
            output_port &= 0b11111101; // Set bit 1 to 0 to power off the 3.3V
        }
    }else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
    this->writeTCA9536Register(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG"), output_port);
    std::this_thread::sleep_for(std::chrono::milliseconds(10)); // wait 10ms
}

double I2CMezzDrivers::HDMezzDriver::readRailVoltage(const uint8_t &afeBlock, const std::string &rail){
    uint16_t bus_voltage_reg_value = this->readINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_" + rail + "_ADDR"), "VBUS");
    double bus_voltage = ((double)bus_voltage_reg_value)*1.6e-3; // Each bit represents 1.6mV
    return bus_voltage;
}

double I2CMezzDrivers::HDMezzDriver::readRailCurrent(const uint8_t &afeBlock, const std::string &rail){
    int16_t current_reg_value = this->readINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_" + rail + "_ADDR"), "CURRENT");
    double current = 0.0;
    if(rail == "5V"){
        current = static_cast<double>(current_reg_value)*this->current_lsb_5V[afeBlock]*1000; // mA
    }
    else if(rail == "3V3"){
        current = static_cast<double>(current_reg_value)*this->current_lsb_3V3[afeBlock]*1000; // mA
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
    return current;
}

double I2CMezzDrivers::HDMezzDriver::readRailPower(const uint8_t &afeBlock, const std::string &rail){
    uint16_t power_reg_value = this->readINA232Function(afeBlock, I2C_drivers_defines::HDMezzAddressMap.at("INA232_" + rail + "_ADDR"), "POWER");
    double power = 0.0;
    if(rail == "5V"){
        power = 32*((double)power_reg_value)*this->current_lsb_5V[afeBlock]*1000; // 1mW/LSB
    }
    else if(rail == "3V3"){
        power = 32*((double)power_reg_value)*this->current_lsb_3V3[afeBlock]*1000; // 1mW/LSB
    }
    else{
        throw std::invalid_argument("Invalid rail name. Valid values are '5V' or '3V3'.");
    }
    return power;
}

void I2CMezzDrivers::HDMezzDriver::selectAfeBlock(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    std::this_thread::sleep_for(std::chrono::milliseconds(10)); // wait 10ms
}

uint16_t I2CMezzDrivers::HDMezzDriver::readINA232Register(const uint8_t &afeBlock, const uint8_t &deviceAddress, const uint8_t &registerAddress){
    this->selectAfeBlock(afeBlock);
    I2CDevice INA232("/dev/i2c-2", deviceAddress);
    std::vector<uint8_t> register_bytes;
    INA232.readBytes(registerAddress, register_bytes, 2);
    return (static_cast<uint16_t>(register_bytes[0]) << 8) | static_cast<uint16_t>(register_bytes[1]);
}

void I2CMezzDrivers::HDMezzDriver::writeINA232Register(const uint8_t &afeBlock, const uint8_t &deviceAddress, const uint8_t &registerAddress, const uint16_t &value){
    this->selectAfeBlock(afeBlock);
    I2CDevice INA232("/dev/i2c-2", deviceAddress);
    std::vector<uint8_t> register_bytes(2);
    register_bytes[0] = (value >> 8) & 0xFF;
    register_bytes[1] = value & 0xFF;
    INA232.writeBytes(registerAddress, register_bytes);
    std::this_thread::sleep_for(std::chrono::milliseconds(10)); // wait 10ms
}

uint16_t I2CMezzDrivers::HDMezzDriver::readINA232Function(const uint8_t &afeBlock, const uint8_t &deviceAddress, const std::string &functionName){
    const auto it = I2C_drivers_defines::INA232FunctionDict.find(functionName);
    if(it == I2C_drivers_defines::INA232FunctionDict.end()){
        throw std::invalid_argument("Invalid INA232 function name: " + functionName);
    }
    
    const auto& bit_field = it->second;
	const auto& registerAddr = bit_field.begin()->first;
	const auto& msb_pos = bit_field.begin()->second.first;
	const auto& lsb_pos = bit_field.begin()->second.second;
    uint16_t register_value = this->readINA232Register(afeBlock, deviceAddress, registerAddr);
    uint16_t function_value = (register_value >> lsb_pos) & ((1 << (msb_pos - lsb_pos + 1)) - 1);
    return function_value;
}

void I2CMezzDrivers::HDMezzDriver::writeINA232Function(const uint8_t &afeBlock, const uint8_t &deviceAddress, const std::string &functionName, const uint16_t &value){
    const auto it = I2C_drivers_defines::INA232FunctionDict.find(functionName);
    if(it == I2C_drivers_defines::INA232FunctionDict.end()){
        throw std::invalid_argument("Invalid INA232 function name: " + functionName);
    }
    
    const auto& bit_field = it->second;
    const auto& registerAddr = bit_field.begin()->first;
    const auto& msb_pos = bit_field.begin()->second.first;
    const auto& lsb_pos = bit_field.begin()->second.second;

    uint16_t register_value = this->readINA232Register(afeBlock, deviceAddress, registerAddr);
    uint16_t mask = ((1 << (msb_pos - lsb_pos + 1)) - 1) << lsb_pos;
    register_value = (register_value & ~mask) | ((value << lsb_pos) & mask);
    this->writeINA232Register(afeBlock, deviceAddress, registerAddr, register_value);
    // readback and confirm the value was written correctly with the register value
    uint16_t readback_register_value = this->readINA232Register(afeBlock, deviceAddress, registerAddr);
    if(readback_register_value != register_value){
        std::ostringstream oss;
        oss << "Failed to write value to INA232 function " << functionName << " in AFE block "
        << static_cast<int>(afeBlock)
        << ", register 0x" << std::hex << std::uppercase << std::setw(2) << std::setfill('0') << static_cast<int>(registerAddr)
        << ". Expected Register Value: 0x" << std::setw(4) << static_cast<int>(register_value)
        << ", Readback Register Value: 0x" << std::setw(4) << static_cast<int>(readback_register_value);
        throw std::runtime_error(oss.str());
    }
}

uint16_t I2CMezzDrivers::HDMezzDriver::readTCA9536Register(const uint8_t &afeBlock, const uint8_t &registerAddress){
    this->selectAfeBlock(afeBlock);
    I2CDevice TCA9536("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_ADDR"));
    uint8_t register_value;
    TCA9536.readByte(registerAddress, register_value);
    return register_value;
}

void I2CMezzDrivers::HDMezzDriver::writeTCA9536Register(const uint8_t &afeBlock, const uint8_t &registerAddress, const uint8_t &value){
    this->selectAfeBlock(afeBlock);
    I2CDevice TCA9536("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_ADDR"));
    TCA9536.writeByte(registerAddress, value);
    std::this_thread::sleep_for(std::chrono::milliseconds(10)); // wait 10ms
    // readback and confirm the value was written correctly
    uint8_t readback_value;
    TCA9536.readByte(registerAddress, readback_value);
    if(readback_value != value){
        std::ostringstream oss;
        oss << "Failed to write value to TCA9536 register in AFE block "
        << static_cast<int>(afeBlock)
        << ", register 0x" << std::hex << std::uppercase << std::setw(2) << std::setfill('0') << static_cast<int>(registerAddress)
        << ". Expected: 0x" << std::setw(2) << static_cast<int>(value)
        << ", Readback: 0x" << std::setw(2) << static_cast<int>(readback_value);
        throw std::runtime_error(oss.str());
    }
}

I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::PJT004A0X43_SRZ_Driver():
    REG_3VD3("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_3VD3"), 1),
    REG_2VA1("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_2VA1"), 1),
    REG_3VA6("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_3VA6"), 1),
    REG_1VD8("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_1VD8"), 1){}


I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::~PJT004A0X43_SRZ_Driver(){}

double I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::readRailVoltage(const uint8_t &regulatorNumber){
    if(regulatorNumber > 3){
        throw std::invalid_argument("Invalid regulator number. Valid values are 0 to 3.");
    }
    uint16_t voltage_reg;
    switch(regulatorNumber){
        case 0:
            voltage_reg = this->REG_3VD3.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_VOUT"));
            break;
        case 1:
            voltage_reg = this->REG_2VA1.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_VOUT"));
            break;
        case 2:
            voltage_reg = this->REG_3VA6.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_VOUT"));
            break;
        case 3:
            voltage_reg = this->REG_1VD8.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_VOUT"));
            break;
        default:
            throw std::invalid_argument("Invalid regulator number. Valid values are 0 to 3.");
    };
    // Now. this value is the mantissa and the exponent is fixed to -9.
    double voltage = decodeRaw(voltage_reg, -9);
    return voltage;
}

double I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::readRailCurrent(const uint8_t &regulatorNumber){
    if(regulatorNumber > 3){
        throw std::invalid_argument("Invalid regulator number. Valid values are 0 to 3.");
    }
    uint16_t current_reg;
    switch(regulatorNumber){
        case 0:
            current_reg = this->REG_3VD3.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_IOUT"));
            break;
        case 1:
            current_reg = this->REG_2VA1.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_IOUT"));
            break;
        case 2:
            current_reg = this->REG_3VA6.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_IOUT"));
            break;
        case 3:
            current_reg = this->REG_1VD8.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_IOUT"));
            break;
        default:
            throw std::invalid_argument("Invalid regulator number. Valid values are 0 to 3.");
    }
    // Now. this value is the mantissa and the exponent is fixed to -9.
    double current = decodeRaw(current_reg, 11, 10);
    return current;
}

double I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::readTemperature(const uint8_t &regulatorNumber){
    if(regulatorNumber > 3){
        throw std::invalid_argument("Invalid regulator number. Valid values are 0 to 3.");
    }
    uint16_t temperature_reg;
    switch(regulatorNumber){
        case 0:
            temperature_reg = this->REG_3VD3.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_TEMPERATURE_2"));
            break;
        case 1:
            temperature_reg = this->REG_2VA1.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_TEMPERATURE_2"));
            break;
        case 2:
            temperature_reg = this->REG_3VA6.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_TEMPERATURE_2"));
            break;
        case 3:
            temperature_reg = this->REG_1VD8.readWordSMBus(I2C_drivers_defines::PJT004A0X43_SRZ_RegisterMAP.at("READ_TEMPERATURE_2"));
            break;
        default:
            throw std::invalid_argument("Invalid regulator number. Valid values are 0 to 3.");
    }
    // Now. this value is the mantissa and the exponent is fixed to -8.
    double temperature = decodeRaw(temperature_reg, 11, 10);
    return temperature;
}

double I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::decodeRaw(const uint16_t &rawData, const uint16_t &exponentLSBPos, const uint16_t &mantissaMSBPos) 
{
    // Extract mantissa
    uint16_t mantissaMask = (1u << (mantissaMSBPos + 1)) - 1u;
    int16_t mantissa = static_cast<int16_t>(rawData & mantissaMask);

    // Sign-extend mantissa
    int mantissaBits = mantissaMSBPos + 1;
    if (mantissa & (1 << (mantissaBits - 1))) {
        mantissa |= ~((1 << mantissaBits) - 1);
    }

    // Extract exponent
    uint16_t exponentMask = ~mantissaMask;
    int16_t exponent = static_cast<int16_t>((rawData & exponentMask) >> exponentLSBPos);

    // Sign-extend exponent
    int exponentBits = 16 - exponentLSBPos;
    if (exponent & (1 << (exponentBits - 1))) {
        exponent |= ~((1 << exponentBits) - 1);
    }

    return static_cast<double>(mantissa) * std::pow(2.0, exponent);
}

double I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver::decodeRaw(const uint16_t &rawData, const int &exponent) 
{
    int16_t mantissa = static_cast<int16_t>(rawData);

    return static_cast<double>(mantissa) * std::pow(2.0, exponent);
}

I2CADCsDrivers::ADS7138_Driver::ADS7138_Driver(const uint8_t &deviceAddress):
    deviceAddress(deviceAddress),
    ADC_ADS7138("/dev/i2c-1", deviceAddress){
        this->configureDevice();
    }

I2CADCsDrivers::ADS7138_Driver::~ADS7138_Driver(){}

uint8_t I2CADCsDrivers::ADS7138_Driver::getChannelsListByte(const std::vector<bool> &channelsList){
    if(channelsList.size() != 8){
        throw std::invalid_argument("Channels list must have exactly 8 elements.");
    }
    uint8_t result = 0;
    for(size_t i = 0; i < channelsList.size(); ++i){
        if(channelsList[i]){
            result |= (1 << i);
        }
    }
    return result;
}

void I2CADCsDrivers::ADS7138_Driver::resetDevice(){

    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG), 0b00000001);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    uint8_t general_config = this->readSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG)); // just to ensure the write is done.
    // check only the bite 0
    auto start_time = std::chrono::high_resolution_clock::now();
    while(general_config & 0b00000001){
        general_config = this->readSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG));
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        // timeout condition
        if(std::chrono::high_resolution_clock::now() - start_time > std::chrono::milliseconds(100)){
            throw std::runtime_error("Timeout waiting for ADS7138 reset to complete.");
        }
    }
}

void I2CADCsDrivers::ADS7138_Driver::calibrateOffsetError(){
    // Set the CALIBRATE bit in the GENERAL_CFG register
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG), 0b00000010);
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    uint8_t general_config = this->readSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG)); // just to ensure the write is done.
    // check only the bite 1
    auto start_time = std::chrono::high_resolution_clock::now();
    while(general_config & 0b00000010){
        general_config = this->readSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::GENERAL_CFG));
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        // timeout condition
        if(std::chrono::high_resolution_clock::now() - start_time > std::chrono::milliseconds(100)){
            throw std::runtime_error("Timeout waiting for ADS7138 offset error calibration to complete.");
        }
    }
}

void I2CADCsDrivers::ADS7138_Driver::configureDevice(){

    this->resetDevice();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::PIN_CFG), 0b0); // set all pins to analog
    // do the offset error calibration first.
    this->calibrateOffsetError();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    
    // Now, I need to configure the channels that will be read in the auto sequence.
    //First convert the std::vector<bool> to a byte.
    uint8_t channel_config = this->getChannelsListByte(this->enabled_channels);
    //then set the auto sequence register with this value.
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::AUTO_SEQ_CH_SEL), channel_config);
    // Set the oversampling ratio to 128 samples (maximum).
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::OSR_CFG), 0b00000111);
    // Sets the SEQ_CONFIG = 0b01 and SEQ_START = 0b1
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::SEQUENCE_CFG), 0b00010001);
    
    //Let's set the device sampling rate and manual mode.
    this->writeSingleRegister(static_cast<uint8_t>(I2C_drivers_defines::ADS7138RegisterMap::OPMODE_CFG), 0b00001000);// sets to 62.5kSPS / High speed oscillator / Manual mode
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
    // Now, the device should be ready to acquire data.

}

void I2CADCsDrivers::ADS7138_Driver::setEnabledChannels(const std::vector<bool> &channelsList){
    if(channelsList.size() != 8){
        throw std::invalid_argument("Channels list must have exactly 8 elements.");
    }
    this->enabled_channels = channelsList;
    uint8_t channel_config = this->getChannelsListByte(this->enabled_channels);
    //then set the auto sequence register with this value.
    this->configureDevice();
}

std::vector<bool> I2CADCsDrivers::ADS7138_Driver::getEnabledChannels() const{
    return this->enabled_channels;
}

void I2CADCsDrivers::ADS7138_Driver::writeSingleRegister(const uint8_t &registerAddress, const uint8_t &value){
    
    // First let's set the data frame. The data frame is composed of:
    // - 1 byte for the opcode
    // - 1 byte for regaddr
    // - 1 byte for data

    std::vector<uint8_t> dataFrame = {static_cast<uint8_t>(I2C_drivers_defines::ADS7138OpCodes::SINGLE_REGISTER_WRITE),
                                      registerAddress,
                                      value};
    this->ADC_ADS7138.writeFrame(dataFrame);
}

uint8_t I2CADCsDrivers::ADS7138_Driver::readSingleRegister(const uint8_t &registerAddress){
    // First let's set the data frame. The data frame is composed of:
    // - 1 byte for the opcode
    // - 1 byte for regaddr
    std::vector<uint8_t> dataFrame = {static_cast<uint8_t>(I2C_drivers_defines::ADS7138OpCodes::SINGLE_REGISTER_READ),
                                      registerAddress};
    this->ADC_ADS7138.writeFrame(dataFrame);
    std::vector<uint8_t> registerValue;
    this->ADC_ADS7138.readFrame(registerValue, 1);
    return registerValue[0];
}

std::vector<double> I2CADCsDrivers::ADS7138_Driver::readData(const uint8_t &numSamples){

    if(numSamples == 0){
        throw std::invalid_argument("Number of samples must be greater than zero.");
    }
    // First, let's determine how many channels are enabled.
    size_t numEnabledChannels = 0;
    for(const auto &channel : this->enabled_channels){
        if(channel){
            numEnabledChannels++;
        }
    }
    if(numEnabledChannels == 0){
        throw std::runtime_error("No channels are enabled. Please enable at least one channel before reading data.");
    }
    // Each sample consists of 2 bytes per channel.
    size_t bytesToRead = numSamples * numEnabledChannels * 2;
    std::vector<uint8_t> rawData(bytesToRead);
    this->ADC_ADS7138.readFrame(rawData, bytesToRead);
    // Now, let's parse the raw data into a vector of double.
    std::vector<double> parsedData;
    parsedData.reserve(numSamples * numEnabledChannels);
    double Vref = 3.3;
    int N = 16;
    for(size_t i = 0; i < bytesToRead; i += 2){
        uint16_t sample = (static_cast<uint16_t>(rawData[i]) << 8) | static_cast<uint16_t>(rawData[i + 1]);
        double voltage = (static_cast<double>(sample) * Vref) / (1u << N);
        parsedData.push_back(voltage);
    }
    return parsedData;
}
