#ifndef I2CDEVICE_HPP
#define I2CDEVICE_HPP

#include <iostream>
#include <string>
#include <vector>
#include <stdexcept>
#include <cstddef>
#include <cstdint>

class I2CRegisterDevice {
public:
    virtual ~I2CRegisterDevice() = default;

    virtual void writeSingleByte(uint8_t data) = 0;
    virtual void writeByte(uint8_t regAddress, uint8_t data) = 0;
    virtual void writeBytes(uint8_t regAddress, const std::vector<uint8_t> &data) = 0;
    virtual void readSingleByte(uint8_t &data) = 0;
    virtual void readByte(uint8_t regAddress, uint8_t &data) = 0;
    virtual void readBytes(uint8_t regAddress, std::vector<uint8_t> &data, std::size_t numBytes) = 0;
};

class I2CDevice : public I2CRegisterDevice {
public:
    // Constructor
    explicit I2CDevice(const std::string &devicePath, uint8_t deviceAddress);
    I2CDevice(const std::string &devicePath, uint8_t deviceAddress, int enablePEC);

    I2CDevice(const I2CDevice&) = delete;
    I2CDevice& operator=(const I2CDevice&) = delete;

    // Destructor
    ~I2CDevice() override;
    
    void writeSingleByte(uint8_t data) override; // Writes a single byte to the device without specifying a register address
    void writeByte(uint8_t regAddress, uint8_t data) override;
    void writeBytes(uint8_t regAddress, const std::vector<uint8_t> &data) override;
    void writeFrame(const std::vector<uint8_t> &data);
    void readSingleByte(uint8_t &data) override; // Reads a single byte from the device without specifying a register address
    void readByte(uint8_t regAddress, uint8_t &data) override;
    void readBytes(uint8_t regAddress, std::vector<uint8_t> &data, std::size_t numBytes) override;
    void readFrame(std::vector<uint8_t> &data, std::size_t numBytes);
    uint16_t readWordSMBus(uint8_t command);
    void writeWordSMBus(uint8_t command, uint16_t value);

private:
    
    int fileDescriptor{-1};
    std::string devicePath;
    uint8_t deviceAddress;

    int  openDevice();
    int  openDevice(int enablePEC);
    bool closeDevice() noexcept;
};

#endif // I2CDEVICE_HPP
