#include "I2CDevice.hpp"

#ifdef __linux__
extern "C" {
#include <i2c/smbus.h>
}
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <iomanip>
#include <limits>
#include <sstream>
#include <system_error>
#include <sys/ioctl.h>
#include <unistd.h>

#include <linux/i2c.h>
#include <linux/i2c-dev.h>

namespace {

std::string i2c_context(const std::string& action,
                        const std::string& device_path,
                        uint8_t device_address,
                        int register_address = -1) {
    std::ostringstream os;
    os << action << " on " << device_path << " address 0x"
       << std::hex << std::uppercase << std::setw(2) << std::setfill('0')
       << static_cast<unsigned>(device_address);
    if (register_address >= 0) {
        os << " register 0x" << std::setw(2)
           << static_cast<unsigned>(register_address);
    }
    return os.str();
}

std::system_error i2c_error(const std::string& action,
                            const std::string& device_path,
                            uint8_t device_address,
                            int error_number,
                            int register_address = -1) {
    return std::system_error(
        error_number,
        std::generic_category(),
        i2c_context(action, device_path, device_address, register_address));
}

std::system_error i2c_transfer_error(const std::string& action,
                                     const std::string& device_path,
                                     uint8_t device_address,
                                     int register_address,
                                     std::size_t expected,
                                     long long actual,
                                     int error_number) {
    std::ostringstream os;
    os << i2c_context(action, device_path, device_address, register_address)
       << ": transferred " << actual << " of " << expected;
    return std::system_error(error_number, std::generic_category(), os.str());
}

ssize_t retrying_write(int file_descriptor, const void* data, std::size_t size) {
    ssize_t result;
    do {
        result = ::write(file_descriptor, data, size);
    } while (result < 0 && errno == EINTR);
    return result;
}

ssize_t retrying_read(int file_descriptor, void* data, std::size_t size) {
    ssize_t result;
    do {
        result = ::read(file_descriptor, data, size);
    } while (result < 0 && errno == EINTR);
    return result;
}

}  // namespace

I2CDevice::I2CDevice(const std::string &devicePath, uint8_t deviceAddress)
    : devicePath(devicePath), deviceAddress(deviceAddress) {
    if (deviceAddress > 0x7F) {
        throw std::invalid_argument("I2CDevice requires a 7-bit slave address");
    }
    fileDescriptor = this->openDevice();
}

I2CDevice::I2CDevice(const std::string &devicePath, uint8_t deviceAddress, int enablePEC)
    : devicePath(devicePath), deviceAddress(deviceAddress) {
    if (deviceAddress > 0x7F) {
        throw std::invalid_argument("I2CDevice requires a 7-bit slave address");
    }
    fileDescriptor = this->openDevice(enablePEC);
}

I2CDevice::~I2CDevice() {
    closeDevice();
}

int I2CDevice::openDevice() {
    int open_flags = O_RDWR;
#ifdef O_CLOEXEC
    open_flags |= O_CLOEXEC;
#endif
    int file;
    do {
        file = open(devicePath.c_str(), open_flags);
    } while (file < 0 && errno == EINTR);
    if (file < 0) {
        const int error_number = errno;
        throw i2c_error("Opening I2C adapter", devicePath, deviceAddress, error_number);
    }

    if (ioctl(file, I2C_SLAVE, deviceAddress) < 0) {
        const int error_number = errno;
        close(file);
        throw i2c_error("Selecting I2C slave", devicePath, deviceAddress, error_number);
    }
    return file;
}

int I2CDevice::openDevice(int enablePEC) {
    const int file = openDevice();
    if (enablePEC != 0) {
        unsigned long functions = 0;
        if (ioctl(file, I2C_FUNCS, &functions) < 0) {
            const int error_number = errno;
            close(file);
            throw i2c_error("Querying I2C adapter capabilities", devicePath, deviceAddress, error_number);
        }
        const unsigned long required = I2C_FUNC_SMBUS_PEC | I2C_FUNC_SMBUS_WORD_DATA;
        if ((functions & required) != required) {
            close(file);
            throw std::runtime_error(
                i2c_context("Enabling PEC (adapter lacks SMBus PEC/word-data support)",
                            devicePath, deviceAddress));
        }
    }

    if (ioctl(file, I2C_PEC, enablePEC) < 0) {
        const int error_number = errno;
        close(file);
        throw i2c_error("Configuring SMBus PEC", devicePath, deviceAddress, error_number);
    }

    return file;
}

bool I2CDevice::closeDevice() noexcept {
    if (fileDescriptor < 0) {
        return true;
    }
    const int file = fileDescriptor;
    fileDescriptor = -1;
    if (close(file) < 0) {
        std::cerr << "Error closing I2C device: " << strerror(errno) << std::endl;
        return false;
    }
    return true;
}

void I2CDevice::writeSingleByte(uint8_t data){
    const ssize_t result = retrying_write(fileDescriptor, &data, 1);
    if(result != 1){
        const int error_number = (result < 0) ? errno : EIO;
        throw i2c_transfer_error("Writing byte", devicePath, deviceAddress,
                                 -1, 1, result, error_number);
    }
}

void I2CDevice::writeByte(uint8_t regAddress, uint8_t data){
    uint8_t buffer[2] = {regAddress, data};
    const ssize_t result = retrying_write(fileDescriptor, buffer, 2);
    if(result != 2){
        const int error_number = (result < 0) ? errno : EIO;
        throw i2c_transfer_error("Writing register", devicePath, deviceAddress,
                                 regAddress, 2, result, error_number);
    }
}

void I2CDevice::writeBytes(uint8_t regAddress, const std::vector<uint8_t> &data){
    std::vector<uint8_t> buffer(data.size() + 1);
    buffer[0] = regAddress;
    std::copy(data.begin(), data.end(), buffer.begin() + 1);
    const ssize_t result = retrying_write(fileDescriptor, buffer.data(), buffer.size());
    if(result != static_cast<ssize_t>(buffer.size())){
        const int error_number = (result < 0) ? errno : EIO;
        throw i2c_transfer_error("Writing register", devicePath, deviceAddress,
                                 regAddress, buffer.size(), result, error_number);
    }
}

void I2CDevice::writeFrame(const std::vector<uint8_t> &data){
    const ssize_t result = retrying_write(fileDescriptor, data.data(), data.size());
    if(result != static_cast<ssize_t>(data.size())){
        const int error_number = (result < 0) ? errno : EIO;
        throw i2c_transfer_error("Writing frame", devicePath, deviceAddress,
                                 -1, data.size(), result, error_number);
    }
}

void I2CDevice::readSingleByte(uint8_t &data){
    uint8_t value = 0;
    const ssize_t result = retrying_read(fileDescriptor, &value, 1);
    if (result != 1) {
        const int error_number = (result < 0) ? errno : EIO;
        throw i2c_transfer_error("Reading byte", devicePath, deviceAddress,
                                 -1, 1, result, error_number);
    }
    data = value;
}

void I2CDevice::readByte(uint8_t regAddress, uint8_t &data){
    std::vector<uint8_t> bytes;
    readBytes(regAddress, bytes, 1);
    data = bytes[0];
}

void I2CDevice::readBytes(uint8_t regAddress, std::vector<uint8_t> &data, std::size_t numBytes){
    if (numBytes == 0) {
        data.clear();
        return;
    }
    if (numBytes > std::numeric_limits<decltype(i2c_msg::len)>::max()) {
        throw std::length_error("Combined I2C register read exceeds i2c_msg length");
    }

    std::vector<uint8_t> received(numBytes);

    uint8_t register_address = regAddress;
    i2c_msg messages[2]{};
    messages[0].addr = deviceAddress;
    messages[0].flags = 0;
    messages[0].len = 1;
    messages[0].buf = &register_address;
    messages[1].addr = deviceAddress;
    messages[1].flags = I2C_M_RD;
    messages[1].len = static_cast<decltype(i2c_msg::len)>(numBytes);
    messages[1].buf = received.data();

    i2c_rdwr_ioctl_data transaction{};
    transaction.msgs = messages;
    transaction.nmsgs = 2;
    int result;
    do {
        result = ioctl(fileDescriptor, I2C_RDWR, &transaction);
    } while (result < 0 && errno == EINTR);
    if (result != 2) {
        const int error_number = (result < 0) ? errno : EIO;
        throw i2c_transfer_error("Combined I2C register read", devicePath, deviceAddress,
                                 regAddress, 2, result, error_number);
    }
    data.swap(received);
}

void I2CDevice::readFrame(std::vector<uint8_t> &data, std::size_t numBytes){
    std::vector<uint8_t> received(numBytes);
    const ssize_t result = retrying_read(fileDescriptor, received.data(), numBytes);
    if (result != static_cast<ssize_t>(numBytes)) {
        const int error_number = (result < 0) ? errno : EIO;
        throw i2c_transfer_error("Reading frame", devicePath, deviceAddress,
                                 -1, numBytes, result, error_number);
    }
    data.swap(received);
}

uint16_t I2CDevice::readWordSMBus(uint8_t command) {
    auto res = i2c_smbus_read_word_data(fileDescriptor, command);
    if (res < 0) {
        const int error_number = errno;
        throw i2c_error("Reading SMBus word", devicePath, deviceAddress,
                        error_number, command);
    }
    return static_cast<uint16_t>(res);
}

void I2CDevice::writeWordSMBus(uint8_t command, uint16_t value) {
    if (i2c_smbus_write_word_data(fileDescriptor, command, value) < 0) {
        const int error_number = errno;
        throw i2c_error("Writing SMBus word", devicePath, deviceAddress,
                        error_number, command);
    }
}

#else

namespace {
[[noreturn]] void not_supported() {
    throw std::runtime_error("I2CDevice is supported only on Linux");
}
}  // namespace

I2CDevice::I2CDevice(const std::string&, uint8_t) { not_supported(); }
I2CDevice::I2CDevice(const std::string&, uint8_t, int) { not_supported(); }
I2CDevice::~I2CDevice() = default;
void I2CDevice::writeSingleByte(uint8_t) { not_supported(); }
void I2CDevice::writeByte(uint8_t, uint8_t) { not_supported(); }
void I2CDevice::writeBytes(uint8_t, const std::vector<uint8_t>&) { not_supported(); }
void I2CDevice::writeFrame(const std::vector<uint8_t>&) { not_supported(); }
void I2CDevice::readSingleByte(uint8_t&) { not_supported(); }
void I2CDevice::readByte(uint8_t, uint8_t&) { not_supported(); }
void I2CDevice::readBytes(uint8_t, std::vector<uint8_t>&, std::size_t) { not_supported(); }
void I2CDevice::readFrame(std::vector<uint8_t>&, std::size_t) { not_supported(); }
uint16_t I2CDevice::readWordSMBus(uint8_t) { not_supported(); }
void I2CDevice::writeWordSMBus(uint8_t, uint16_t) { not_supported(); }

#endif
