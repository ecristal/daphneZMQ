#include "SpyBufferFreshness.hpp"
#include "SpyBufferReadoutInhibitGuard.hpp"

#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void testEngageAndRelease() {
    std::vector<uint32_t> writes;
    SpyBufferReadoutInhibitGuard guard(
        [&writes](uint32_t value) {
            writes.push_back(value);
            return value;
        });

    guard.engage();
    guard.release();

    require(
        writes == std::vector<uint32_t>({1, 0}),
        "Normal guard sequence must write HIGH followed by LOW");
}

void testIncompatibleFirmwareIsRejected() {
    std::vector<uint32_t> writes;
    bool rejected = false;

    try {
        SpyBufferReadoutInhibitGuard guard(
            [&writes](uint32_t value) {
                writes.push_back(value);
                return 0u;
            });
        guard.engage();
    } catch (const std::runtime_error&) {
        rejected = true;
    }

    require(rejected, "Missing inhibit readback must reject the firmware");
    require(
        writes == std::vector<uint32_t>({1, 0}),
        "Failed assertion must make a best-effort inhibit clear");
}

void testExceptionClearsInhibit() {
    std::vector<uint32_t> writes;

    try {
        SpyBufferReadoutInhibitGuard guard(
            [&writes](uint32_t value) {
                writes.push_back(value);
                return value;
            });
        guard.engage();
        throw std::runtime_error("simulated extraction failure");
    } catch (const std::runtime_error&) {
    }

    require(
        writes == std::vector<uint32_t>({1, 0}),
        "Stack unwinding must clear an engaged inhibit");
}

void testThrowingAssertionStillAttemptsClear() {
    std::vector<uint32_t> writes;
    bool rejected = false;

    try {
        SpyBufferReadoutInhibitGuard guard(
            [&writes](uint32_t value) -> uint32_t {
                writes.push_back(value);
                if (value == 1) {
                    throw std::runtime_error("simulated MMIO write failure");
                }
                return 0;
            });
        guard.engage();
    } catch (const std::runtime_error&) {
        rejected = true;
    }

    require(rejected, "A throwing HIGH write must propagate its error");
    require(
        writes == std::vector<uint32_t>({1, 0}),
        "A throwing HIGH write must still make a best-effort clear");
}

void testFailedReleaseIsRetriedByDestructor() {
    std::vector<uint32_t> writes;
    unsigned clear_attempts = 0;
    bool release_failed = false;

    {
        SpyBufferReadoutInhibitGuard guard(
            [&writes, &clear_attempts](uint32_t value) {
                writes.push_back(value);
                if (value == 1) {
                    return 1u;
                }
                return clear_attempts++ == 0 ? 1u : 0u;
            });
        guard.engage();
        try {
            guard.release();
        } catch (const std::runtime_error&) {
            release_failed = true;
        }
    }

    require(release_failed, "Bad LOW readback must be reported");
    require(
        writes == std::vector<uint32_t>({1, 0, 0}),
        "Destructor must retry a failed inhibit clear");
}

void testFirstHardwareRequestWaitsPastCurrentTimestamp() {
    using Timestamp = std::array<uint16_t, 4>;
    const Timestamp current = {1, 2, 3, 4};

    const Timestamp baseline = selectExternalTriggerBaseline(
        current,
        std::optional<Timestamp>{});

    require(
        baseline == current,
        "First hardware request must use current timestamp as its baseline");
}

void testHardwareRequestAcceptsAlreadyNewerTimestamp() {
    using Timestamp = std::array<uint16_t, 4>;
    const Timestamp delivered = {1, 2, 3, 4};
    const Timestamp current = {2, 2, 3, 4};

    const Timestamp baseline = selectExternalTriggerBaseline(
        current,
        std::optional<Timestamp>{delivered});

    require(
        baseline == delivered && current != baseline,
        "Hardware request must retain the last delivery as baseline");
}

}  // namespace

int main() {
    try {
        testEngageAndRelease();
        testIncompatibleFirmwareIsRejected();
        testExceptionClearsInhibit();
        testThrowingAssertionStillAttemptsClear();
        testFailedReleaseIsRetriedByDestructor();
        testFirstHardwareRequestWaitsPastCurrentTimestamp();
        testHardwareRequestAcceptsAlreadyNewerTimestamp();
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }

    return 0;
}
