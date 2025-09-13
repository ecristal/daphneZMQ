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

void I2CMezzDrivers::HDMezzDriver::setRShunt5V(const uint8_t &afeBlock, const double &rShunt){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rShunt <= 0){
        throw std::invalid_argument("Invalid Rshunt value. It must be greater than zero.");
    }
    this->r_shunt_5V[afeBlock] = rShunt;
    configureCalibrationValues();
}

void I2CMezzDrivers::HDMezzDriver::setRShunt3V3(const uint8_t &afeBlock, const double &rShunt){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(rShunt <= 0){
        throw std::invalid_argument("Invalid Rshunt value. It must be greater than zero.");
    }
    this->r_shunt_3V3[afeBlock] = rShunt;
    configureCalibrationValues();
}

void I2CMezzDrivers::HDMezzDriver::setMaxCurrent5VScale(const uint8_t &afeBlock, const double &maxCurrent){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(maxCurrent <= 0){
        throw std::invalid_argument("Invalid Max Current Scale value. It must be greater than zero.");
    }
    this->max_current_5V_scale[afeBlock] = maxCurrent;
    configureCalibrationValues();
}

void I2CMezzDrivers::HDMezzDriver::setMaxCurrent3V3Scale(const uint8_t &afeBlock, const double &maxCurrent){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(maxCurrent <= 0){
        throw std::invalid_argument("Invalid Max Current Scale value. It must be greater than zero.");
    }
    this->max_current_3V3_scale[afeBlock] = maxCurrent;
    configureCalibrationValues();
}

void I2CMezzDrivers::HDMezzDriver::setMaxCurrent5VShutdown(const uint8_t &afeBlock, const double &maxCurrent){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(maxCurrent <= 0){
        throw std::invalid_argument("Invalid Max Current Shutdown value. It must be greater than zero.");
    }
    this->max_current_5V_shutdown[afeBlock] = maxCurrent;
    configureCalibrationValues();
}

void I2CMezzDrivers::HDMezzDriver::setMaxCurrent3V3Shutdown(const uint8_t &afeBlock, const double &maxCurrent){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(maxCurrent <= 0){
        throw std::invalid_argument("Invalid Max Current Shutdown value. It must be greater than zero.");
    }
    this->max_current_3V3_shutdown[afeBlock] = maxCurrent;
    configureCalibrationValues();
}

double I2CMezzDrivers::HDMezzDriver::getRShunt5V(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->r_shunt_5V[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getRShunt3V3(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->r_shunt_3V3[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxCurrent5VScale(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->max_current_5V_scale[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxCurrent3V3Scale(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->max_current_3V3_scale[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxCurrent5VShutdown(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->max_current_5V_shutdown[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxCurrent3V3Shutdown(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->max_current_3V3_shutdown[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxPower5V(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->max_power_5V[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getMaxPower3V3(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->max_power_3V3[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getCurrentLsb5V(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->current_lsb_5V[afeBlock];
}

double I2CMezzDrivers::HDMezzDriver::getCurrentLsb3V3(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->current_lsb_3V3[afeBlock];
}

uint16_t I2CMezzDrivers::HDMezzDriver::getShuntCal5V(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->shunt_cal_5V[afeBlock];
}

uint16_t I2CMezzDrivers::HDMezzDriver::getShuntCal3V3(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    return this->shunt_cal_3V3[afeBlock];
}

void I2CMezzDrivers::HDMezzDriver::configureHdMezzAfeBlock(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    // Configure the calibration register for 5V
    // Now we need to create a local device to write to the specific HD Mezz digital devices.
    I2CDevice INA232_5V("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"));
    I2CDevice INA232_3V3("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"));
    I2CDevice TCA9536("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_ADDR"));
    // Now, let's configure the INA232 for 5V. It should be sended in big endian
    // shunt calibration register
    std::vector<uint8_t> shunt_cal_5V_bytes = {
        static_cast<uint8_t>((this->shunt_cal_5V[afeBlock] >> 8) & 0xFF),
        static_cast<uint8_t>(this->shunt_cal_5V[afeBlock] & 0xFF)
    };

    INA232_5V.writeBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_CALIBRATION_REG"), shunt_cal_5V_bytes);
    usleep(10000); // wait 10ms

    // maximum power register (5V)
    uint16_t max_power_5V_reg = (uint16_t)(this->max_power_5V[afeBlock] / (32*this->current_lsb_5V[afeBlock]));
    std::vector<uint8_t> max_power_5_vector ={
        static_cast<uint8_t>((max_power_5V_reg >> 8) & 0xFF),
        static_cast<uint8_t>(max_power_5V_reg & 0xFF)
    };
    INA232_5V.writeBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_ALERT_LIMIT_REG"), max_power_5_vector);
    usleep(10000); // wait 10ms

    //Alert flags
    std::vector<uint8_t> alert_flags_vector = {
        static_cast<uint8_t>((this->enable_alert_flags >> 8) & 0xFF),
        static_cast<uint8_t>(this->enable_alert_flags & 0xFF)
    };
    INA232_5V.writeBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_MASK_ENABLE_REG"), alert_flags_vector);
    usleep(10000); // wait 10ms
    
    // Now, let's configure the INA232 for 3.3V.
    // shunt calibration register
    std::vector<uint8_t> shunt_cal_3V3_bytes = {
        static_cast<uint8_t>((this->shunt_cal_3V3[afeBlock] >> 8) & 0xFF),
        static_cast<uint8_t>(this->shunt_cal_3V3[afeBlock] & 0xFF)
    };
    INA232_3V3.writeBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_CALIBRATION_REG"), shunt_cal_3V3_bytes);
    usleep(10000); // wait 10ms

    // maximum power register (3.3V)
    uint16_t max_power_3V3_reg = (uint16_t)(this->max_power_3V3[afeBlock] / (32*this->current_lsb_3V3[afeBlock]));
    std::vector<uint8_t> max_power_3V3_vector ={
        static_cast<uint8_t>((max_power_3V3_reg >> 8) & 0xFF),
        static_cast<uint8_t>(max_power_3V3_reg & 0xFF)
    };
    INA232_3V3.writeBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_ALERT_LIMIT_REG"), max_power_3V3_vector);
    usleep(10000); // wait 10ms

    //Alert flags
    INA232_3V3.writeBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_MASK_ENABLE_REG"), alert_flags_vector);
    usleep(10000); // wait 10ms

    // Now, let's configure the TCA9536
    TCA9536.writeByte(I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_CONF_REG"), 0xF0); // Set all pins as outputs
    usleep(10000); // wait 10ms

}

void I2CMezzDrivers::HDMezzDriver::powerOn_5V_HDMezzAfeBlock(const uint8_t &afeBlock, const bool &powerOn){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    I2CDevice TCA9536("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_ADDR"));
    uint8_t output_port;
    TCA9536.readByte(I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG"), output_port);
    if(powerOn){ 
        output_port |= 0b00000001; // Set bit 0 to 1 to power on the 5V
    } else {
        output_port &= 0b11111110; // Set bit 0 to 0 to power off the 5V
    }
    TCA9536.writeByte(I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG"), output_port);
    usleep(10000); // wait 10ms
}

void I2CMezzDrivers::HDMezzDriver::powerOn_3V3_HDMezzAfeBlock(const uint8_t &afeBlock, const bool &powerOn){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    I2CDevice TCA9536("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_ADDR"));
    uint8_t output_port;
    TCA9536.readByte(I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG"), output_port);
    if(powerOn){ 
        output_port |= 0b00000010; // Set bit 1 to 1 to power on the 3.3V
    } else {
        output_port &= 0b11111101; // Set bit 1 to 0 to power off the 3.3V
    }
    TCA9536.writeByte(I2C_drivers_defines::HDMezzAddressMap.at("TCA9536_OUTPUT_PORT_REG"), output_port);
    usleep(10000); // wait 10ms
}

double I2CMezzDrivers::HDMezzDriver::readRailVoltage5V(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    I2CDevice INA232_5V("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"));
    std::vector<uint8_t> bus_voltage_bytes;
    INA232_5V.readBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_BUS_VOLTAGE_REG"), bus_voltage_bytes, 2);
    uint16_t bus_voltage_reg = (static_cast<uint16_t>(bus_voltage_bytes[0]) << 8) | static_cast<uint16_t>(bus_voltage_bytes[1]);
    double bus_voltage = ((double)bus_voltage_reg)*1.6e-3; // Each bit represents 1.6mV
    return bus_voltage;
}

double I2CMezzDrivers::HDMezzDriver::readRailVoltage3V3(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    I2CDevice INA232_3V3("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"));
    std::vector<uint8_t> bus_voltage_bytes;
    INA232_3V3.readBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_BUS_VOLTAGE_REG"), bus_voltage_bytes, 2);
    uint16_t bus_voltage_reg = (static_cast<uint16_t>(bus_voltage_bytes[0]) << 8) | static_cast<uint16_t>(bus_voltage_bytes[1]);
    double bus_voltage = ((double)bus_voltage_reg)*1.6e-3; // Each bit represents 1.6mV
    return bus_voltage;
}

double I2CMezzDrivers::HDMezzDriver::readRailCurrent5V(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    I2CDevice INA232_5V("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"));
    std::vector<uint8_t> current_bytes;
    INA232_5V.readBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_CURRENT_REG"), current_bytes, 2);
    uint16_t current_reg = (static_cast<uint16_t>(current_bytes[0]) << 8) | static_cast<uint16_t>(current_bytes[1]);
    double current = ((double)current_reg)*this->current_lsb_5V[afeBlock]*1000; // 1mA/LSB
    return current;
}

double I2CMezzDrivers::HDMezzDriver::readRailCurrent3V3(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    I2CDevice INA232_3V3("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"));
    std::vector<uint8_t> current_bytes;
    INA232_3V3.readBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_CURRENT_REG"), current_bytes, 2);
    uint16_t current_reg = (static_cast<uint16_t>(current_bytes[0]) << 8) | static_cast<uint16_t>(current_bytes[1]);
    double current = ((double)current_reg)*this->current_lsb_3V3[afeBlock]*1000; // 1mA/LSB
    return current;
}

double I2CMezzDrivers::HDMezzDriver::readRailPower5V(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    I2CDevice INA232_5V("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("INA232_5V_ADDR"));
    std::vector<uint8_t> power_bytes;
    INA232_5V.readBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_POWER_REG"), power_bytes, 2);
    uint16_t power_reg = (static_cast<uint16_t>(power_bytes[0]) << 8) | static_cast<uint16_t>(power_bytes[1]);
    double power = 32*((double)power_reg)*this->current_lsb_5V[afeBlock]*1000; // 1mW/LSB
    return power;
}

double I2CMezzDrivers::HDMezzDriver::readRailPower3V3(const uint8_t &afeBlock){
    if(afeBlock > 4){
        throw std::invalid_argument("Invalid AFE block number. Valid values are 0 to 4.");
    }
    if(!this->enabled_afeBlocks[afeBlock]){
        throw std::runtime_error("AFE block " + std::to_string(afeBlock) + " is not enabled. Please enable it before configuration.");
    }
    std::string afeBlockStr = "AFE" + std::to_string(afeBlock) + "_MEZZ";
    I2C_exp_mezz.writeSingleByte(I2C_drivers_defines::HDMezzExpanderEncoder.at(afeBlockStr)); // Configuration the switch to the specific AFE block
    usleep(10000); // wait 10ms
    I2CDevice INA232_3V3("/dev/i2c-2", I2C_drivers_defines::HDMezzAddressMap.at("INA232_3V3_ADDR"));
    std::vector<uint8_t> power_bytes;
    INA232_3V3.readBytes(I2C_drivers_defines::HDMezzAddressMap.at("INA232_POWER_REG"), power_bytes, 2);
    uint16_t power_reg = (static_cast<uint16_t>(power_bytes[0]) << 8) | static_cast<uint16_t>(power_bytes[1]);
    double power = 32*((double)power_reg)*this->current_lsb_3V3[afeBlock]*1000; // 1mW/LSB
    return power;
}

I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver::PJT004A0X43_SRZ_Driver():
    REG_3VD3("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_3VD3"), 1),
    REG_2VA1("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_2VA1"), 1),
    REG_3VA6("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_3VA6"), 1),
    REG_1VD8("/dev/i2c-2", I2C_drivers_defines::I2CDevicesAddress.at("SW_REG_1VD8"), 1){}


I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver::~PJT004A0X43_SRZ_Driver(){}

double I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver::readRailVoltage(const uint8_t &regulatorNumber){
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

double I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver::readRailCurrent(const uint8_t &regulatorNumber){
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

double I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver::readTemperature(const uint8_t &regulatorNumber){
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

double I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver::decodeRaw(const uint16_t &rawData, const uint16_t &exponentLSBPos, const uint16_t &mantissaMSBPos) 
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

double I2CRegulartorsDrivers::PJT004A0X43_SRZ_Driver::decodeRaw(const uint16_t &rawData, const int &exponent) 
{
    int16_t mantissa = static_cast<int16_t>(rawData);

    return static_cast<double>(mantissa) * std::pow(2.0, exponent);
}

