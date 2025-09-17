#ifndef I2CDEVICE_HPP
#define I2CDEVICE_HPP

#include <iostream>
#include <string>
#include <vector>
#include <stdexcept>
#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/i2c-dev.h>
#include <cerrno>
#include <cstring>

class I2CDevice {
public:
    // Constructor
    I2CDevice(const std::string &devicePath, const uint8_t &deviceAddress);
    I2CDevice(const std::string &devicePath, const uint8_t &deviceAddress, const int &enablePEC);

    // Destructor
    ~I2CDevice();
    
    void writeSingleByte(const uint8_t &data); // Writes a single byte to the device without specifying a register address
    void writeByte(const uint8_t &regAddress, const uint8_t &data);
    void writeBytes(const uint8_t &regAddress, const std::vector<uint8_t> &data);
    void writeFrame(std::vector<uint8_t> &data);
    void readSingleByte(uint8_t &data); // Reads a single byte from the device without specifying a register address
    void readByte(const uint8_t &regAddress, uint8_t &data);
    void readBytes(const uint8_t &regAddress, std::vector<uint8_t> &data, const uint8_t &numBytes);
    void readFrame(std::vector<uint8_t> &data, const uint8_t &numBytes);
    uint16_t readWordSMBus(const uint8_t &command);
    void writeWordSMBus(const uint8_t &command, uint16_t value);

private:
    
    int fileDescriptor;
    std::string devicePath;
    uint8_t deviceAddress;

    int openDevice();
    int openDevice(const int &enablePEC);
    bool closeDevice();
};

#endif // I2CDEVICE_HPP