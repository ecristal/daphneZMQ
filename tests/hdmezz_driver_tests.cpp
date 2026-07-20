#include "DaphneI2CDrivers.hpp"

#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <functional>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace {

constexpr uint8_t kMuxAddress = 0x71;
constexpr uint8_t kIna3V3Address = 0x40;
constexpr uint8_t kTcaAddress = 0x41;
constexpr uint8_t kIna5VAddress = 0x42;

struct Event {
    enum class Kind { Select, Read, Write };

    Kind kind;
    uint8_t afe;
    uint8_t address;
    int registerAddress;
    std::vector<uint8_t> bytes;
};

struct FakeBusState {
    std::mutex mutex;
    uint8_t selectedAfe{0xFF};
    std::array<std::array<uint16_t, 256>, 5> ina3V3{};
    std::array<std::array<uint16_t, 256>, 5> ina5V{};
    std::array<std::array<uint8_t, 256>, 5> tca{};
    std::vector<Event> events;
    unsigned statusCounter{0};
    bool varyDynamicStatusBits{true};
    bool corruptMaskWritableBit{false};
    bool yieldAfterSelect{false};

    FakeBusState() {
        for (std::size_t afe = 0; afe < 5; ++afe) {
            ina3V3[afe][0x00] = 0x4127;
            ina5V[afe][0x00] = 0x4127;
            ina3V3[afe][0x3E] = 0x5449;
            ina5V[afe][0x3E] = 0x5449;
            tca[afe][0x01] = 0xFF;
            tca[afe][0x03] = 0xFF;
        }
    }
};

class FakeDevice final : public I2CRegisterDevice {
public:
    FakeDevice(std::shared_ptr<FakeBusState> state, uint8_t address)
        : state_(std::move(state)), address_(address) {}

    void writeSingleByte(uint8_t data) override {
        if (address_ != kMuxAddress) {
            throw std::runtime_error("single-byte write is only valid for the fake mux");
        }
        const uint8_t afe = decodeMux(data);
        bool shouldYield = false;
        {
            std::lock_guard<std::mutex> lock(state_->mutex);
            state_->selectedAfe = afe;
            state_->events.push_back(
                Event{Event::Kind::Select, afe, address_, -1, {data}});
            shouldYield = state_->yieldAfterSelect;
        }
        if (shouldYield) {
            std::this_thread::yield();
        }
    }

    void writeByte(uint8_t registerAddress, uint8_t data) override {
        std::lock_guard<std::mutex> lock(state_->mutex);
        const uint8_t afe = selectedAfeLocked();
        if (address_ != kTcaAddress) {
            throw std::runtime_error("byte write is only valid for the fake TCA9536");
        }
        state_->tca[afe][registerAddress] = data;
        state_->events.push_back(
            Event{Event::Kind::Write, afe, address_, registerAddress, {data}});
    }

    void writeBytes(uint8_t registerAddress, const std::vector<uint8_t>& data) override {
        std::lock_guard<std::mutex> lock(state_->mutex);
        const uint8_t afe = selectedAfeLocked();
        if (!isIna() || data.size() != 2) {
            throw std::runtime_error("word write is only valid for a fake INA232");
        }
        const uint16_t value = static_cast<uint16_t>(
            (static_cast<uint16_t>(data[0]) << 8) | data[1]);
        inaRegistersLocked(afe)[registerAddress] = value;
        state_->events.push_back(
            Event{Event::Kind::Write, afe, address_, registerAddress, data});
    }

    void readSingleByte(uint8_t&) override {
        throw std::runtime_error("fake current-pointer reads are unsupported");
    }

    void readByte(uint8_t registerAddress, uint8_t& data) override {
        std::lock_guard<std::mutex> lock(state_->mutex);
        const uint8_t afe = selectedAfeLocked();
        if (address_ != kTcaAddress) {
            throw std::runtime_error("byte read is only valid for the fake TCA9536");
        }
        data = state_->tca[afe][registerAddress];
        state_->events.push_back(
            Event{Event::Kind::Read, afe, address_, registerAddress, {data}});
    }

    void readBytes(
        uint8_t registerAddress,
        std::vector<uint8_t>& data,
        std::size_t numBytes) override {
        std::lock_guard<std::mutex> lock(state_->mutex);
        const uint8_t afe = selectedAfeLocked();
        if (!isIna() || numBytes != 2) {
            throw std::runtime_error("word read is only valid for a fake INA232");
        }
        uint16_t value = inaRegistersLocked(afe)[registerAddress];
        if (registerAddress == 0x06 && state_->varyDynamicStatusBits) {
            value = static_cast<uint16_t>(
                (value & ~0x003Cu) | ((state_->statusCounter++ & 0x0Fu) << 2));
        }
        if (registerAddress == 0x06 && state_->corruptMaskWritableBit) {
            value ^= 0x0800u;
        }
        std::vector<uint8_t> received = {
            static_cast<uint8_t>((value >> 8) & 0xFF),
            static_cast<uint8_t>(value & 0xFF)
        };
        state_->events.push_back(
            Event{Event::Kind::Read, afe, address_, registerAddress, received});
        data.swap(received);
    }

private:
    static uint8_t decodeMux(uint8_t encoded) {
        for (uint8_t afe = 0; afe < 5; ++afe) {
            if (encoded == static_cast<uint8_t>(1u << afe)) {
                return afe;
            }
        }
        throw std::runtime_error("invalid fake mux selection");
    }

    uint8_t selectedAfeLocked() const {
        if (state_->selectedAfe >= 5) {
            throw std::runtime_error("downstream access without mux selection");
        }
        return state_->selectedAfe;
    }

    bool isIna() const {
        return address_ == kIna3V3Address || address_ == kIna5VAddress;
    }

    std::array<uint16_t, 256>& inaRegistersLocked(uint8_t afe) {
        return address_ == kIna5VAddress ? state_->ina5V[afe] : state_->ina3V3[afe];
    }

    std::shared_ptr<FakeBusState> state_;
    uint8_t address_;
};

struct Rig {
    std::shared_ptr<FakeBusState> state;
    std::unique_ptr<I2CMezzDrivers::HDMezzDriver> driver;
};

Rig makeRig() {
    auto state = std::make_shared<FakeBusState>();
    auto factory = [state](const std::string& path, uint8_t address) {
        if (path != "fake-i2c") {
            throw std::runtime_error("unexpected fake adapter path");
        }
        return std::make_unique<FakeDevice>(state, address);
    };
    auto driver = std::make_unique<I2CMezzDrivers::HDMezzDriver>(
        "fake-i2c", std::move(factory), [](std::chrono::milliseconds) {});
    return Rig{std::move(state), std::move(driver)};
}

std::vector<Event> events(const std::shared_ptr<FakeBusState>& state) {
    std::lock_guard<std::mutex> lock(state->mutex);
    return state->events;
}

void clearEvents(const std::shared_ptr<FakeBusState>& state) {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->events.clear();
}

int failures = 0;

void check(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void checkNear(double actual, double expected, double tolerance, const std::string& message) {
    if (!std::isfinite(actual) || !std::isfinite(expected) ||
        !(std::abs(actual - expected) <= tolerance)) {
        throw std::runtime_error(
            message + ": expected " + std::to_string(expected) +
            ", got " + std::to_string(actual));
    }
}

template <typename Function>
void expectThrows(Function&& function, const std::string& message) {
    try {
        function();
    } catch (const std::exception&) {
        return;
    }
    throw std::runtime_error(message);
}

template <typename Function>
void run(const char* name, Function&& function) {
    try {
        function();
        std::cout << "[PASS] " << name << '\n';
    } catch (const std::exception& error) {
        ++failures;
        std::cerr << "[FAIL] " << name << ": " << error.what() << '\n';
    }
}

void enableAndConfigure(Rig& rig, uint8_t afe) {
    rig.driver->enableAfeBlock(afe, true);
    rig.driver->configureHdMezzAfeBlock(afe);
}

void verifyEachTransferFollowsSelection(const std::vector<Event>& log) {
    for (std::size_t index = 0; index < log.size(); ++index) {
        if (log[index].kind == Event::Kind::Select) {
            check(log[index].bytes.size() == 1, "mux event has no encoded selection");
            check(log[index].bytes[0] == static_cast<uint8_t>(1u << log[index].afe),
                  "mux selected the wrong one-hot channel");
            continue;
        }
        check(index > 0, "downstream transfer occurred without an earlier selection");
        check(log[index - 1].kind == Event::Kind::Select,
              "downstream transfer did not immediately follow mux selection");
        check(log[index - 1].afe == log[index].afe,
              "mux selection and downstream transfer used different AFE blocks");
    }
}

void testMuxAndSafeInitialization() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(2, true);
    check(rig.driver->isAfeBlockEnabled(2), "enabled block was not recorded");
    check(!rig.driver->isAfeBlockConfigured(2), "enable unexpectedly marked block configured");

    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[2][0x01] & 0x03u) == 0,
              "safe initialization did not clear both rail requests");
        check((rig.state->tca[2][0x03] & 0x0Fu) == 0x0Cu,
              "TCA P0/P1 are not outputs with P2/P3 left as inputs");
    }

    const auto log = events(rig.state);
    verifyEachTransferFollowsSelection(log);
    std::size_t outputWrite = log.size();
    std::size_t configWrite = log.size();
    for (std::size_t index = 0; index < log.size(); ++index) {
        if (log[index].kind != Event::Kind::Write || log[index].address != kTcaAddress) {
            continue;
        }
        if (log[index].registerAddress == 0x01 && outputWrite == log.size()) {
            outputWrite = index;
            check((log[index].bytes.at(0) & 0x03u) == 0,
                  "first TCA output write requested a rail");
        }
        if (log[index].registerAddress == 0x03 && configWrite == log.size()) {
            configWrite = index;
            check(log[index].bytes.at(0) == 0xFC,
                  "safe TCA configuration was not 0xFC");
        }
    }
    check(outputWrite < configWrite,
          "TCA directions changed before the rail output latches were cleared");
}

void testAllMuxEncodings() {
    auto rig = makeRig();
    for (uint8_t afe = 0; afe < 5; ++afe) {
        rig.driver->probeAfeBlock(afe);
    }
    verifyEachTransferFollowsSelection(events(rig.state));
}

void testProbeRejectsWrongIdentityAfterSafeOff() {
    auto rig = makeRig();
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->ina5V[3][0x3E] = 0x1234;
    }
    expectThrows(
        [&] { rig.driver->enableAfeBlock(3, true); },
        "wrong INA232 identity was accepted");
    check(!rig.driver->isAfeBlockEnabled(3),
          "failed probe left the block enabled");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[3][0x01] & 0x03u) == 0,
              "failed identity probe left stale rail requests active");
    }
    for (const auto& event : events(rig.state)) {
        if (event.kind == Event::Kind::Write) {
            check(event.address == kTcaAddress,
                  "failed identity probe programmed an INA232");
        }
    }
}

void testDefaultConfigurationAndByteOrder() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(0, true);
    clearEvents(rig.state);
    rig.driver->configureHdMezzAfeBlock(0);
    check(rig.driver->isAfeBlockConfigured(0),
          "successful configuration was not recorded");

    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check(rig.state->ina5V[0][0x00] == 0x4127, "wrong 5V INA configuration");
        check(rig.state->ina3V3[0][0x00] == 0x4127, "wrong 3V3 INA configuration");
        check(rig.state->ina5V[0][0x05] == 0x5B05, "wrong default 5V SHUNT_CAL");
        check(rig.state->ina3V3[0][0x05] == 0x0AEC, "wrong default 3V3 SHUNT_CAL");
        check(rig.state->ina5V[0][0x07] == 0x06C0, "wrong default 5V SOL limit");
        check(rig.state->ina3V3[0][0x07] == 0x04B0, "wrong default 3V3 SOL limit");
        check(rig.state->ina5V[0][0x06] == 0x8001, "wrong 5V mask/enable");
        check(rig.state->ina3V3[0][0x06] == 0x8001, "wrong 3V3 mask/enable");
        check((rig.state->tca[0][0x01] & 0x03u) == 0, "configuration left a rail requested");
    }

    bool sawBigEndianCalibration = false;
    const auto log = events(rig.state);
    verifyEachTransferFollowsSelection(log);
    for (const auto& event : log) {
        if (event.kind == Event::Kind::Write &&
            event.address == kIna5VAddress &&
            event.registerAddress == 0x05 &&
            event.bytes == std::vector<uint8_t>({0x5B, 0x05})) {
            sawBigEndianCalibration = true;
        }
    }
    check(sawBigEndianCalibration, "INA232 word was not written most-significant byte first");
}

void testWritableReadbackMismatchFailsConfiguration() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(0, true);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->corruptMaskWritableBit = true;
    }
    expectThrows(
        [&] { rig.driver->configureHdMezzAfeBlock(0); },
        "writable mask-bit mismatch was accepted");
    check(!rig.driver->isAfeBlockConfigured(0),
          "failed readback left the block configured");
}

void testConfigurationForcesRailsOffBeforeInaWrites() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(2, true);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->tca[2][0x01] |= 0x03u;
        rig.state->corruptMaskWritableBit = true;
    }
    clearEvents(rig.state);
    expectThrows(
        [&] { rig.driver->configureHdMezzAfeBlock(2); },
        "injected late INA verification fault was not detected");

    const auto log = events(rig.state);
    std::size_t railOffWrite = log.size();
    std::size_t firstInaWrite = log.size();
    for (std::size_t index = 0; index < log.size(); ++index) {
        if (log[index].kind != Event::Kind::Write) {
            continue;
        }
        if (log[index].address == kTcaAddress &&
            log[index].registerAddress == 0x01 &&
            (log[index].bytes.at(0) & 0x03u) == 0 &&
            railOffWrite == log.size()) {
            railOffWrite = index;
        }
        if ((log[index].address == kIna5VAddress ||
             log[index].address == kIna3V3Address) &&
            firstInaWrite == log.size()) {
            firstInaWrite = index;
        }
    }
    check(railOffWrite < firstInaWrite,
          "INA programming began before both rail requests were forced off");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[2][0x01] & 0x03u) == 0,
              "partial configuration failure left a rail requested");
    }
    check(!rig.driver->isAfeBlockConfigured(2),
          "partial configuration failure left configured state true");
}

void testPerBlockPowerStateAndSafeDisable() {
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    enableAndConfigure(rig, 1);
    rig.driver->setPowerRequests(0, true, false);

    const auto state0 = rig.driver->readPowerRequests(0);
    const auto state1 = rig.driver->readPowerRequests(1);
    check(state0.power5V && !state0.power3V3,
          "block 0 power request was not read from its TCA");
    check(!state1.power5V && !state1.power3V3,
          "block 0 power request leaked into block 1");

    rig.driver->enableAfeBlock(0, false);
    check(!rig.driver->isAfeBlockEnabled(0), "disable did not clear enabled state");
    check(!rig.driver->isAfeBlockConfigured(0), "disable did not clear configured state");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[0][0x01] & 0x03u) == 0,
              "disable did not force both rail requests off");
    }
}

void testDisableEnforcesOffWhenAlreadyDisabled() {
    auto rig = makeRig();
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->tca[4][0x01] = 0xFF;
    }
    rig.driver->enableAfeBlock(4, false);
    check(!rig.driver->isAfeBlockEnabled(4),
          "idempotent disable changed software enabled state");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[4][0x01] & 0x03u) == 0,
              "idempotent disable did not enforce both requests OFF");
        check((rig.state->tca[4][0x03] & 0x0Fu) == 0x0Cu,
              "idempotent disable did not establish safe GPIO directions");
    }
}

void testPowerOnRequiresConfiguration() {
    auto rig = makeRig();
    rig.driver->enableAfeBlock(4, true);
    clearEvents(rig.state);
    expectThrows(
        [&] { rig.driver->setPowerRequests(4, true, false); },
        "unconfigured block accepted an ON request");
    check(events(rig.state).empty(),
          "rejected ON request accessed downstream hardware");
}

void testAlertReadImmediatelyRemovesRailRequests() {
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    rig.driver->setPowerRequests(0, true, true);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->varyDynamicStatusBits = false;
        rig.state->ina5V[0][0x06] |= 0x0010u;
    }
    check(rig.driver->checkAlertStatus(0, "5V"),
          "asserted INA232 AFF was not reported");
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        check((rig.state->tca[0][0x01] & 0x03u) == 0,
              "AFF read did not immediately remove both rail requests");
    }
}

void testSignedCurrentDecode() {
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->ina5V[0][0x04] = 0xFFFF;
    }
    const double expected = -rig.driver->getCurrentLsb(0, "5V") * 1000.0;
    checkNear(rig.driver->readRailCurrent(0, "5V"), expected, 1e-12,
              "negative INA232 current wrapped around");
}

void testInvalidConfigurationIsNonMutatingAndDoesNoIo() {
    auto rig = makeRig();
    const double originalRShunt = rig.driver->getRShunt(0, "5V");
    const double originalScale = rig.driver->getMaxCurrentScale(0, "5V");
    const double originalShutdown = rig.driver->getMaxCurrentShutdown(0, "5V");
    clearEvents(rig.state);

    expectThrows(
        [&] { rig.driver->setRShunt(0, std::numeric_limits<double>::quiet_NaN(), "5V"); },
        "NaN Rshunt was accepted");
    expectThrows(
        [&] { rig.driver->setMaxCurrentScale(0, std::numeric_limits<double>::infinity(), "5V"); },
        "infinite current scale was accepted");
    expectThrows(
        [&] { rig.driver->setMaxCurrentShutdown(0, 0.3, "5V"); },
        "shutdown above scale was accepted");
    expectThrows(
        [&] { rig.driver->setRShunt(0, 0.5, "5V"); },
        "shunt full-scale overflow was accepted");
    expectThrows(
        [&] { rig.driver->setRShunt(0, 1e-9, "5V"); },
        "calibration register overflow was accepted");

    checkNear(rig.driver->getRShunt(0, "5V"), originalRShunt, 0.0,
              "invalid Rshunt mutated driver state");
    checkNear(rig.driver->getMaxCurrentScale(0, "5V"), originalScale, 0.0,
              "invalid current scale mutated driver state");
    checkNear(rig.driver->getMaxCurrentShutdown(0, "5V"), originalShutdown, 0.0,
              "invalid shutdown mutated driver state");
    check(events(rig.state).empty(),
          "numeric validation performed I2C traffic");
}

void testDisabledReadsDoNoIo() {
    auto rig = makeRig();
    clearEvents(rig.state);
    expectThrows(
        [&] { (void)rig.driver->readRailVoltage(1, "5V"); },
        "disabled block telemetry was allowed");
    expectThrows(
        [&] { (void)rig.driver->readPowerRequests(1); },
        "disabled block power state was allowed");
    check(events(rig.state).empty(),
          "disabled block rejection accessed the bus");
}

void testConcurrentMuxTransactionsStayCoherent() {
    auto rig = makeRig();
    enableAndConfigure(rig, 0);
    enableAndConfigure(rig, 1);
    {
        std::lock_guard<std::mutex> lock(rig.state->mutex);
        rig.state->ina5V[0][0x02] = 0x0100;
        rig.state->ina5V[1][0x02] = 0x0200;
        rig.state->yieldAfterSelect = true;
    }
    clearEvents(rig.state);

    std::atomic<bool> coherent{true};
    const auto reader = [&](uint8_t afe, double expected) {
        try {
            for (int iteration = 0; iteration < 500; ++iteration) {
                if (std::abs(rig.driver->readRailVoltage(afe, "5V") - expected) > 1e-12) {
                    coherent.store(false);
                }
            }
        } catch (const std::exception&) {
            coherent.store(false);
        }
    };
    std::thread first(reader, static_cast<uint8_t>(0), 0x0100 * 1.6e-3);
    std::thread second(reader, static_cast<uint8_t>(1), 0x0200 * 1.6e-3);
    first.join();
    second.join();

    check(coherent.load(), "concurrent reads crossed mux channels");
    verifyEachTransferFollowsSelection(events(rig.state));
}

}  // namespace

int main() {
    run("mux selection and safe initialization", testMuxAndSafeInitialization);
    run("all mux encodings", testAllMuxEncodings);
    run("probe identity failure after safe-off", testProbeRejectsWrongIdentityAfterSafeOff);
    run("default configuration and byte order", testDefaultConfigurationAndByteOrder);
    run("masked readback verification", testWritableReadbackMismatchFailsConfiguration);
    run("rail-off ordering during configuration", testConfigurationForcesRailsOffBeforeInaWrites);
    run("per-block power state and safe disable", testPerBlockPowerStateAndSafeDisable);
    run("idempotent disable enforces off", testDisableEnforcesOffWhenAlreadyDisabled);
    run("power-on requires configuration", testPowerOnRequiresConfiguration);
    run("alert read removes rail requests", testAlertReadImmediatelyRemovesRailRequests);
    run("signed current decode", testSignedCurrentDecode);
    run("invalid configuration validation", testInvalidConfigurationIsNonMutatingAndDoesNoIo);
    run("disabled block rejection", testDisabledReadsDoNoIo);
    run("concurrent mux transaction coherence", testConcurrentMuxTransactionsStayCoherent);

    if (failures != 0) {
        std::cerr << failures << " HD mezzanine test(s) failed\n";
        return 1;
    }
    std::cout << "All HD mezzanine hardware-layer tests passed\n";
    return 0;
}
