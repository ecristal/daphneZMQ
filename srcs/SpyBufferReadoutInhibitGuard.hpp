#ifndef SPYBUFFER_READOUT_INHIBIT_GUARD_HPP
#define SPYBUFFER_READOUT_INHIBIT_GUARD_HPP

#include <cstdint>
#include <functional>
#include <stdexcept>
#include <utility>

class SpyBufferReadoutInhibitGuard {
public:
    using WriteInhibit = std::function<uint32_t(uint32_t)>;

    explicit SpyBufferReadoutInhibitGuard(WriteInhibit write_inhibit)
        : write_inhibit_(std::move(write_inhibit)) {
        if (!write_inhibit_) {
            throw std::invalid_argument(
                "Spybuffer inhibit write callback is empty");
        }
    }

    SpyBufferReadoutInhibitGuard(
        const SpyBufferReadoutInhibitGuard&) = delete;
    SpyBufferReadoutInhibitGuard& operator=(
        const SpyBufferReadoutInhibitGuard&) = delete;

    ~SpyBufferReadoutInhibitGuard() noexcept {
        clearNoThrow();
    }

    void engage() {
        engaged_ = true;
        uint32_t readback = 0;
        try {
            readback = write_inhibit_(1);
        } catch (...) {
            clearNoThrow();
            throw;
        }
        if (readback != 1) {
            clearNoThrow();
            throw std::runtime_error(
                "Spybuffer readout inhibit did not assert; "
                "the loaded firmware is incompatible");
        }
    }

    void release() {
        if (!engaged_) {
            return;
        }

        const uint32_t readback = write_inhibit_(0);
        if (readback != 0) {
            throw std::runtime_error(
                "Spybuffer readout inhibit did not clear");
        }
        engaged_ = false;
    }

private:
    void clearNoThrow() noexcept {
        if (!engaged_) {
            return;
        }

        try {
            if (write_inhibit_(0) == 0) {
                engaged_ = false;
            }
        } catch (...) {
        }
    }

    WriteInhibit write_inhibit_;
    bool engaged_{false};
};

#endif  // SPYBUFFER_READOUT_INHIBIT_GUARD_HPP
