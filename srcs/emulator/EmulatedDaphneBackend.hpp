#pragma once

#include <array>
#include <chrono>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>

#include "server_controller/slow_control_backend.hpp"

namespace daphne_sc::emulator {

enum class BoardPhase {
  kPoweredOff,
  kBooting,
  kReady,
  kResettingAfes,
  kPowerSettling,
  kProgrammingChannels,
  kProgrammingAfes,
  kAligning,
  kFailed,
};

const char* to_string(BoardPhase phase);

struct TimingProfile {
  double time_scale = 1.0;
  std::chrono::milliseconds startup_delay{0};
  std::chrono::microseconds afe_reset{100};
  std::chrono::milliseconds afe_power_settle{5};

  // These are deliberately zero until measurements from a physical board are
  // available.  They remain separate knobs because the hardware serializes
  // channel DAC and AFE-register programming.
  std::chrono::microseconds channel_dac_write{0};
  std::chrono::microseconds afe_program{0};

  std::chrono::milliseconds delayctrl_reset{10};
  std::chrono::milliseconds serdes_reset{10};
  std::chrono::milliseconds spy_snapshot{1};
  uint32_t delay_taps = 512;
  uint32_t bitslip_taps = 16;
  uint32_t verification_reads = 4;
  bool auto_align = true;
};

struct ChannelState {
  uint32_t trim = 0;
  uint32_t offset = 0;
  uint32_t gain = 0;
  uint32_t threshold = 0;
  bool configured = false;
  uint64_t record_count = 0;
  uint64_t busy_count = 0;
  uint64_t full_count = 0;
};

struct AfeState {
  uint32_t attenuation = 0;
  uint32_t bias = 0;
  uint32_t delay = 0;
  uint32_t bitslip = 0;
  bool powered = false;
  bool configured = false;
  bool aligned = false;
};

struct TelemetryState {
  std::array<double, 5> bias_voltage{};
  double power_minus5v = 0.0;
  double power_plus2p5v = 0.0;
  double power_ce = 0.0;
  double temperature = 0.0;
};

struct BoardSnapshot {
  BoardPhase phase = BoardPhase::kPoweredOff;
  uint64_t configuration_generation = 0;
  uint32_t bias_control = 0;
  uint32_t trigger_mask_low = 0;
  uint32_t trigger_mask_high = 0;
  std::array<ChannelState, 40> channels{};
  std::array<AfeState, 5> afes{};
  TelemetryState telemetry{};
};

class EmulatedDaphneBackend final : public SlowControlBackend {
 public:
  using SleepFunction = std::function<void(std::chrono::nanoseconds)>;

  explicit EmulatedDaphneBackend(TimingProfile timing = {}, SleepFunction sleeper = {});

  void boot() override;
  daphne::ConfigureResponse configure(const daphne::ConfigureRequest& request) override;
  daphne::ReadTriggerCountersResponse read_trigger_counters(
      const daphne::ReadTriggerCountersRequest& request) const override;
  daphne::TestRegResponse read_test_register() const override;
  daphne::GeneralInfo read_general_info(const daphne::InfoRequest& request) const override;
  daphne::telemetry::v8::ReadTelemetrySnapshotResponse read_telemetry_snapshot(
      const daphne::telemetry::v8::ReadTelemetrySnapshotRequest& request) const override;

  BoardSnapshot snapshot() const;
  void set_telemetry(const TelemetryState& telemetry);
  void set_trigger_counters(uint32_t channel,
                            uint64_t record_count,
                            uint64_t busy_count,
                            uint64_t full_count);

  std::chrono::nanoseconds nominal_configure_duration(
      const daphne::ConfigureRequest& request) const;

 private:
  void sleep_for(std::chrono::nanoseconds duration) const;
  void set_phase(BoardPhase phase);
  daphne::ConfigureResponse configuration_error(const std::string& message);

  TimingProfile timing_;
  SleepFunction sleeper_;
  mutable std::mutex mutex_;
  BoardSnapshot state_;
};

}  // namespace daphne_sc::emulator
