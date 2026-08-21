#include "FpgaRegDict.hpp"

#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

using RegisterMap = FpgaRegDict::RegisterMap;

const RegisterMap::mapped_type& requireRegister(
    const RegisterMap& registers,
    const std::string& name,
    uint32_t expected_address) {
    const auto it = registers.find(name);
    if (it == registers.end()) {
        throw std::runtime_error("Missing register: " + name);
    }
    if (it->second.first != expected_address) {
        throw std::runtime_error("Wrong address for register: " + name);
    }
    return it->second;
}

void requireField(
    const RegisterMap::mapped_type& reg,
    const std::string& field,
    int expected_low,
    int expected_high) {
    const auto it = reg.second.find(field);
    if (it == reg.second.end()) {
        throw std::runtime_error("Missing field: " + field);
    }
    if (it->second.first != expected_low || it->second.second != expected_high) {
        throw std::runtime_error("Wrong bit range for field: " + field);
    }
}

void requireMissing(const RegisterMap& registers, const std::string& name) {
    if (registers.find(name) != registers.end()) {
        throw std::runtime_error("Obsolete register is still present: " + name);
    }
}

}  // namespace

int main() {
    try {
        const FpgaRegDict dictionary;
        const auto& registers = dictionary.getRegisterMap();

        if (registers.size() != 389) {
            throw std::runtime_error(
                "Unexpected number of DAPHNE firmware registers");
        }

        const auto& dac_control =
            requireRegister(registers, "dacGainBiasControl", 0x0C000000);
        requireField(dac_control, "BUSY", 0, 0);
        if (dac_control.second.find("GO") != dac_control.second.end()) {
            throw std::runtime_error("DAC GO is not a readable register field");
        }

        const auto& endpoint_clock =
            requireRegister(registers, "endpointClockControl", 0x04000000);
        requireField(endpoint_clock, "MMCM0_RESET", 0, 0);
        requireField(endpoint_clock, "MMCM1_RESET", 1, 1);

        const auto& sender =
            requireRegister(registers, "tenGigabitSender", 0x18000000);
        requireField(sender, "DATA", 0, 31);

        requireRegister(registers, "adHocTriggerCommand", 0x14000028);
        const auto& st_config =
            requireRegister(registers, "selfTriggerConfig", 0x1400002C);
        requireField(st_config, "VALUE", 0, 13);
        requireField(st_config, "SLOPE_THRESHOLD", 7, 13);
        requireRegister(registers, "selfTriggerSignalDelay", 0x14000030);
        requireRegister(
            registers, "selfTriggerFilterOutputSelector", 0x14000034);
        requireRegister(registers, "selfTriggerCounterReset", 0x14000038);
        requireRegister(
            registers, "selfTriggerCompensatorEnableLow", 0x1400003C);
        requireRegister(
            registers, "selfTriggerCompensatorEnableHigh", 0x14000040);
        requireRegister(
            registers, "selfTriggerInvertEnableLow", 0x14000044);
        requireRegister(
            registers, "selfTriggerInvertEnableHigh", 0x14000048);
        const auto& spy_trigger_control =
            requireRegister(registers, "spyTriggerControl", 0x08000034);
        requireField(spy_trigger_control, "CONTROL", 0, 2);
        requireField(spy_trigger_control, "SOURCE", 0, 1);
        requireField(spy_trigger_control, "INHIBIT", 2, 2);
        requireMissing(registers, "spyReadoutInhibit");

        requireMissing(registers, "idLink");
        requireMissing(registers, "idSlot");
        requireMissing(registers, "idCrate");
        requireMissing(registers, "idDetector");
        requireMissing(registers, "idVersion");
        requireMissing(registers, "selfTriggerFullConfigLow");
        requireMissing(registers, "selfTriggerFullConfigHIGH");
        requireMissing(registers, "matchingTriggerTemplate_0");
        requireMissing(registers, "matchingTriggerTemplate_15");

        const auto& output_status =
            requireRegister(registers, "outputSpyBufferStatus", 0x20000000);
        requireField(output_status, "STREAM_SELECT", 0, 2);
        requireField(output_status, "FSM_STATUS", 28, 31);
        requireRegister(registers, "outputSpyBufferData", 0x20000004);

        for (uint32_t channel = 0; channel < 40; ++channel) {
            const uint32_t offset = channel * 0x20;
            const std::string suffix = "_" + std::to_string(channel);
            const auto& threshold = requireRegister(
                registers,
                "selfTriggerThreshold" + suffix,
                0x20010000 + offset);
            requireField(threshold, "THRESHOLD", 0, 27);
            requireRegister(
                registers,
                "selfTriggerRecordCountLow" + suffix,
                0x20010004 + offset);
            requireRegister(
                registers,
                "selfTriggerRecordCountHigh" + suffix,
                0x20010008 + offset);
            requireRegister(
                registers,
                "selfTriggerBusyCountLow" + suffix,
                0x2001000C + offset);
            requireRegister(
                registers,
                "selfTriggerBusyCountHigh" + suffix,
                0x20010010 + offset);
            requireRegister(
                registers,
                "selfTriggerFullCountLow" + suffix,
                0x20010014 + offset);
            requireRegister(
                registers,
                "selfTriggerFullCountHigh" + suffix,
                0x20010018 + offset);
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }

    return 0;
}
