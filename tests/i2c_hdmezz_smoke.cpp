#include "I2CDevice.hpp"

#include <cstdint>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

uint16_t readWord(I2CDevice& device, uint8_t registerAddress) {
    std::vector<uint8_t> bytes;
    device.readBytes(registerAddress, bytes, 2);
    return static_cast<uint16_t>(
        (static_cast<uint16_t>(bytes.at(0)) << 8) | bytes.at(1));
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const std::string path = argc > 1 ? argv[1] : "/dev/i2c-2";
        const int afeBlock = argc > 2 ? std::stoi(argv[2]) : 0;
        if (afeBlock < 0 || afeBlock > 4) {
            throw std::invalid_argument("AFE block must be in the range 0..4");
        }

        I2CDevice mux(path, 0x71);
        I2CDevice ina3V3(path, 0x40);
        I2CDevice tca9536(path, 0x41);
        I2CDevice ina5V(path, 0x42);
        mux.writeSingleByte(static_cast<uint8_t>(1u << afeBlock));

        const uint16_t id3V3 = readWord(ina3V3, 0x3E);
        const uint16_t id5V = readWord(ina5V, 0x3E);
        uint8_t tcaConfiguration = 0;
        tca9536.readByte(0x03, tcaConfiguration);

        std::cout << "AFE " << afeBlock
                  << ": INA232 IDs 0x" << std::hex << std::uppercase
                  << std::setw(4) << std::setfill('0') << id5V
                  << " / 0x" << std::setw(4) << id3V3
                  << ", TCA9536 config 0x" << std::setw(2)
                  << static_cast<unsigned>(tcaConfiguration) << std::dec << '\n';
        if (id3V3 != 0x5449 || id5V != 0x5449) {
            throw std::runtime_error("Unexpected INA232 manufacturer ID");
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "HD mezzanine I2C smoke test failed: " << error.what() << '\n';
        return 1;
    }
}
