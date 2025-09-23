#include "SpiDevice.hpp"

SpiDevice::SpiDevice(const std::string& devPath, const uint32_t &speedHz,
            const uint8_t &mode, const uint8_t &bitsPerWord)
            : fd(-1),
              speed(speedHz),
              mode(mode),
              bits(bitsPerWord){
    
    fd = open(devPath.c_str(), O_RDWR);
    if (fd < 0) {
        throw std::runtime_error("Failed to open " + devPath + ": " + strerror(errno));
    }

    if (ioctl(fd, SPI_IOC_WR_MODE, &mode) < 0)
        throw std::runtime_error("Failed to set SPI mode: " + std::string(strerror(errno)));

    if (ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits) < 0)
        throw std::runtime_error("Failed to set bits per word: " + std::string(strerror(errno)));

    if (ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed) < 0)
        throw std::runtime_error("Failed to set max speed: " + std::string(strerror(errno)));
}

SpiDevice::~SpiDevice() {
    if (fd >= 0){ 
        close(fd);
    }
}

std::vector<uint8_t> SpiDevice::transfer(const std::vector<uint8_t>& tx) {
    
    std::vector<uint8_t> rx(tx.size(), 0);

    struct spi_ioc_transfer tr = {};
    tr.tx_buf = reinterpret_cast<unsigned long>(tx.data());
    tr.rx_buf = reinterpret_cast<unsigned long>(rx.data());
    tr.len = tx.size();
    tr.speed_hz = speed;
    tr.bits_per_word = bits;

    if (ioctl(fd, SPI_IOC_MESSAGE(1), &tr) < 1) {
        throw std::runtime_error("SPI transfer failed: " + std::string(strerror(errno)));
    }
    return rx;
}

uint32_t SpiDevice::getSpeedHz() const{
    return this->speed;
}

uint8_t SpiDevice::getMode() const{
    return this->mode;
}

uint8_t SpiDevice::getBitsPerWord() const{
    return this->bits;
}