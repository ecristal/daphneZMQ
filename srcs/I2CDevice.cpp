#include "I2CDevice.hpp"
extern "C" {
    #include <i2c/smbus.h>
}

I2CDevice::I2CDevice(const std::string &devicePath, const uint8_t &deviceAddress)
    : devicePath(devicePath), deviceAddress(deviceAddress) {
    fileDescriptor = this->openDevice();
    if (fileDescriptor < 0) {
        // Throw an exception showing which device path and address in hex failed to connect.
        throw std::runtime_error("Failed to open I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
    this->fileDescriptor = fileDescriptor;
}

I2CDevice::I2CDevice(const std::string &devicePath, const uint8_t &deviceAddress, const int &enablePEC)
    : devicePath(devicePath), deviceAddress(deviceAddress) {
    fileDescriptor = this->openDevice(enablePEC);
    if (fileDescriptor < 0) {
        // Throw an exception showing which device path and address in hex failed to connect.
        throw std::runtime_error("Failed to open I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
    this->fileDescriptor = fileDescriptor;
}

I2CDevice::~I2CDevice() {
    closeDevice();
}

int I2CDevice::openDevice() {
    int file = open(devicePath.c_str(), O_RDWR);
    if (file < 0) {
        std::cerr << "Error opening I2C device: " << strerror(errno) << std::endl;
        return -1;
    }

    if (ioctl(file, I2C_SLAVE, deviceAddress) < 0) {
        std::cerr << "Error setting I2C address: " << strerror(errno) << std::endl;
        close(file);
        return -1;
    }
    return file;
}

int I2CDevice::openDevice(const int &enablePEC) {
    int file = open(devicePath.c_str(), O_RDWR);
    if (file < 0) {
        std::cerr << "Error opening I2C device: " << strerror(errno) << std::endl;
        return -1;
    }

    if (ioctl(file, I2C_SLAVE, deviceAddress) < 0) {
        std::cerr << "Error setting I2C address: " << strerror(errno) << std::endl;
        close(file);
        return -1;
    }

    if (ioctl(file, I2C_PEC, enablePEC) < 0) {
        std::cerr << "Warning: Failed to enable PEC: " << strerror(errno) << std::endl;
    }

    return file;
}

bool I2CDevice::closeDevice() {
    if (close(fileDescriptor) < 0) {
        std::cerr << "Error closing I2C device: " << strerror(errno) << std::endl;
        return false;
    }
    return true;
}

void I2CDevice::writeSingleByte(const uint8_t &data){
    int result = write(fileDescriptor, &data, 1);
    if(result != 1){
        throw std::runtime_error("Failed to write single byte to I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
}

void I2CDevice::writeByte(const uint8_t &regAddress, const uint8_t &data){
    uint8_t buffer[2] = {regAddress, data};
    int result = write(fileDescriptor, buffer, 2);
    if(result != 2){
        throw std::runtime_error("Failed to write byte to I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
}

void I2CDevice::writeBytes(const uint8_t &regAddress, const std::vector<uint8_t> &data){
    std::vector<uint8_t> buffer(data.size() + 1);
    buffer[0] = regAddress;
    std::copy(data.begin(), data.end(), buffer.begin() + 1);
    int result = write(fileDescriptor, buffer.data(), buffer.size());
    if(result != static_cast<int>(buffer.size())){
        throw std::runtime_error("Failed to write bytes to I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
}

void I2CDevice::writeFrame(std::vector<uint8_t> &data){
    int result = write(fileDescriptor, data.data(), data.size());
    if(result != static_cast<int>(data.size())){
        throw std::runtime_error("Failed to write bytes to I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
}

void I2CDevice::readSingleByte(uint8_t &data){
    if (read(fileDescriptor, &data, 1) != 1) {
        throw std::runtime_error("Failed to read single byte from I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
}

void I2CDevice::readByte(const uint8_t &regAddress, uint8_t &data){
    if (write(fileDescriptor, &regAddress, 1) != 1) {
        throw std::runtime_error("Failed to write register address to I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
    if (read(fileDescriptor, &data, 1) != 1) {
        throw std::runtime_error("Failed to read byte from I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
}

void I2CDevice::readBytes(const uint8_t &regAddress, std::vector<uint8_t> &data, const uint8_t &numBytes){
    if (write(fileDescriptor, &regAddress, 1) != 1) {
        throw std::runtime_error("Failed to write register address to I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
    data.resize(numBytes);
    if (read(fileDescriptor, data.data(), numBytes) != numBytes) {
        throw std::runtime_error("Failed to read bytes from I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
}

void I2CDevice::readFrame(std::vector<uint8_t> &data, const uint8_t &numBytes){
    data.resize(numBytes);
    if (read(fileDescriptor, data.data(), numBytes) != numBytes) {
        throw std::runtime_error("Failed to read bytes from I2C device at " + devicePath + " with address " + std::to_string(deviceAddress));
    }
}

uint16_t I2CDevice::readWordSMBus(const uint8_t &command) {
    auto res = i2c_smbus_read_word_data(fileDescriptor, command);
    if (res < 0) {
        throw std::runtime_error("Failed to read word with PEC from I2C device at " 
            + devicePath + " addr " + std::to_string(deviceAddress));
    }
    return static_cast<uint16_t>(res);
}

void I2CDevice::writeWordSMBus(const uint8_t &command, uint16_t value) {
    if (i2c_smbus_write_word_data(fileDescriptor, command, value) < 0) {
        throw std::runtime_error("Failed to write word with PEC to I2C device at " 
            + devicePath + " addr " + std::to_string(deviceAddress));
    }
}