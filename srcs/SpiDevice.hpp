#ifndef SPIDEVICE_HPP
#define SPIDEVICE_HPP

#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/spi/spidev.h>
#include <cstring>
#include <cerrno>

class SpiDevice {
public:
    SpiDevice(const std::string& devPath, const uint32_t &speedHz, const uint8_t &mode, const uint8_t &bitsPerWord);

    ~SpiDevice();

    std::vector<uint8_t> transfer(const std::vector<uint8_t>& tx);

    uint32_t getSpeedHz() const;
    uint8_t getMode() const;
    uint8_t getBitsPerWord() const;

private:
    int fd;
    uint32_t speed;
    uint8_t mode;
    uint8_t bits;
};

#endif // SPIDEVICE_HPP
