#include "emulator/EmulatedDaphneBackend.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <vector>

#include "server_controller/v8_telemetry.hpp"
#include "server_controller/v8_telemetry_runtime.hpp"

namespace daphne_sc::emulator {
namespace {

constexpr uint32_t kChannelCount = 40;
constexpr uint32_t kAfeCount = 5;
constexpr uint32_t kThresholdMask = 0x0FFFFFFFu;

std::chrono::nanoseconds multiply_duration(std::chrono::nanoseconds duration, uint64_t count) {
  if (count == 0 || duration.count() == 0) return std::chrono::nanoseconds{0};
  const auto max_count = static_cast<uint64_t>(std::numeric_limits<int64_t>::max());
  const auto duration_count = static_cast<uint64_t>(duration.count());
  if (duration_count > max_count / count) {
    throw std::overflow_error("emulation timing duration overflow");
  }
  return std::chrono::nanoseconds{static_cast<int64_t>(duration_count * count)};
}

}  // namespace

const char* to_string(BoardPhase phase) {
  switch (phase) {
    case BoardPhase::kPoweredOff:
      return "powered-off";
    case BoardPhase::kBooting:
      return "booting";
    case BoardPhase::kReady:
      return "ready";
    case BoardPhase::kResettingAfes:
      return "resetting-afes";
    case BoardPhase::kPowerSettling:
      return "power-settling";
    case BoardPhase::kProgrammingChannels:
      return "programming-channels";
    case BoardPhase::kProgrammingAfes:
      return "programming-afes";
    case BoardPhase::kAligning:
      return "aligning";
    case BoardPhase::kFailed:
      return "failed";
  }
  return "unknown";
}

EmulatedDaphneBackend::EmulatedDaphneBackend(TimingProfile timing, SleepFunction sleeper)
    : timing_(timing), sleeper_(std::move(sleeper)) {
  if (!std::isfinite(timing_.time_scale) || timing_.time_scale < 0.0) {
    throw std::invalid_argument("emulation time scale must be finite and non-negative");
  }
  if (!sleeper_) {
    sleeper_ = [](std::chrono::nanoseconds duration) {
      if (duration.count() > 0) std::this_thread::sleep_for(duration);
    };
  }
}

void EmulatedDaphneBackend::boot() {
  set_phase(BoardPhase::kBooting);
  sleep_for(timing_.startup_delay);
  set_phase(BoardPhase::kReady);
}

daphne::ConfigureResponse EmulatedDaphneBackend::configure(const daphne::ConfigureRequest& request) {
  set_phase(BoardPhase::kResettingAfes);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& afe : state_.afes) {
      afe.powered = false;
      afe.aligned = false;
    }
  }
  sleep_for(timing_.afe_reset);

  set_phase(BoardPhase::kPowerSettling);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto& afe : state_.afes) afe.powered = true;
  }
  sleep_for(timing_.afe_power_settle);

  const uint64_t requested_threshold = request.self_trigger_xcorr() != 0
                                           ? (request.self_trigger_xcorr() & kThresholdMask)
                                           : request.self_trigger_threshold();
  const auto threshold = static_cast<uint32_t>(std::min<uint64_t>(requested_threshold, kThresholdMask));

  uint32_t trigger_mask_low = 0;
  uint32_t trigger_mask_high = 0;
  set_phase(BoardPhase::kProgrammingChannels);
  for (const auto& requested_channel : request.channels()) {
    const uint32_t channel = requested_channel.id();
    if (channel >= kChannelCount) {
      return configuration_error("Channel out of range (0..39): " + std::to_string(channel));
    }

    // The real server performs two serialized DAC writes per channel.
    sleep_for(timing_.channel_dac_write);
    sleep_for(timing_.channel_dac_write);

    {
      std::lock_guard<std::mutex> lock(mutex_);
      auto& target = state_.channels[channel];
      target.trim = requested_channel.trim();
      target.offset = requested_channel.offset();
      target.gain = requested_channel.gain();
      target.threshold = threshold;
      target.configured = true;
    }
    if (channel < 32) {
      trigger_mask_low |= (1u << channel);
    } else {
      trigger_mask_high |= (1u << (channel - 32));
    }
  }

  {
    std::lock_guard<std::mutex> lock(mutex_);
    state_.trigger_mask_low = trigger_mask_low;
    state_.trigger_mask_high = trigger_mask_high;
    state_.bias_control = request.biasctrl();
  }

  set_phase(BoardPhase::kProgrammingAfes);
  for (const auto& requested_afe : request.afes()) {
    const uint32_t afe = requested_afe.id();
    if (afe >= kAfeCount) {
      return configuration_error("AFE out of range (0..4): " + std::to_string(afe));
    }
    if (requested_afe.attenuators() > 4095) {
      return configuration_error("VGAIN out of range for AFE " + std::to_string(afe));
    }
    if (requested_afe.v_bias() > 4095) {
      return configuration_error("BIAS out of range for AFE " + std::to_string(afe));
    }

    sleep_for(timing_.afe_program);
    {
      std::lock_guard<std::mutex> lock(mutex_);
      auto& target = state_.afes[afe];
      target.attenuation = requested_afe.attenuators();
      target.bias = requested_afe.v_bias();
      target.configured = true;
    }
  }

  // configureDaphne() reinforces the AFE power state after programming.
  set_phase(BoardPhase::kPowerSettling);
  sleep_for(timing_.afe_power_settle);

  if (timing_.auto_align) {
    set_phase(BoardPhase::kAligning);
    sleep_for(timing_.delayctrl_reset);
    sleep_for(timing_.serdes_reset);

    const uint64_t snapshots_per_afe = static_cast<uint64_t>(timing_.delay_taps) +
                                       static_cast<uint64_t>(timing_.bitslip_taps) +
                                       static_cast<uint64_t>(timing_.verification_reads);
    const auto per_afe_delay = multiply_duration(timing_.spy_snapshot, snapshots_per_afe);
    for (uint32_t afe = 0; afe < kAfeCount; ++afe) {
      sleep_for(per_afe_delay);
      std::lock_guard<std::mutex> lock(mutex_);
      auto& target = state_.afes[afe];
      target.delay = timing_.delay_taps == 0 ? 0 : timing_.delay_taps / 2;
      target.bitslip = 0;
      target.aligned = true;
    }
  }

  uint64_t generation = 0;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    state_.phase = BoardPhase::kReady;
    generation = ++state_.configuration_generation;
  }

  daphne_sc::telemetry::RecordActiveConfiguration(request);

  const auto nominal_ms =
      std::chrono::duration_cast<std::chrono::milliseconds>(nominal_configure_duration(request)).count();
  daphne::ConfigureResponse response;
  response.set_success(true);
  std::ostringstream message;
  message << "Emulated DAPHNE configuration complete; generation=" << generation
          << "; nominal_duration_ms=" << nominal_ms;
  response.set_message(message.str());
  return response;
}

daphne::ReadTriggerCountersResponse EmulatedDaphneBackend::read_trigger_counters(
    const daphne::ReadTriggerCountersRequest& request) const {
  daphne::ReadTriggerCountersResponse response;
  std::vector<uint32_t> channels;
  if (request.channels_size() == 0) {
    channels.resize(kChannelCount);
    std::iota(channels.begin(), channels.end(), 0);
  } else {
    channels.assign(request.channels().begin(), request.channels().end());
  }

  std::lock_guard<std::mutex> lock(mutex_);
  for (const uint32_t channel : channels) {
    if (channel >= kChannelCount) continue;
    const auto& source = state_.channels[channel];
    auto* target = response.add_snapshots();
    target->set_channel(channel);
    target->set_threshold(source.threshold);
    target->set_record_count(source.record_count);
    target->set_busy_count(source.busy_count);
    target->set_full_count(source.full_count);
  }
  response.set_success(true);
  response.set_message("OK");
  return response;
}

daphne::TestRegResponse EmulatedDaphneBackend::read_test_register() const {
  daphne::TestRegResponse response;
  response.set_value(0xDEADBEEF);
  response.set_message("ok");
  return response;
}

daphne::GeneralInfo EmulatedDaphneBackend::read_general_info(const daphne::InfoRequest&) const {
  std::lock_guard<std::mutex> lock(mutex_);
  daphne::GeneralInfo response;
  response.set_v_bias_0(state_.telemetry.bias_voltage[0]);
  response.set_v_bias_1(state_.telemetry.bias_voltage[1]);
  response.set_v_bias_2(state_.telemetry.bias_voltage[2]);
  response.set_v_bias_3(state_.telemetry.bias_voltage[3]);
  response.set_v_bias_4(state_.telemetry.bias_voltage[4]);
  response.set_power_minus5v(state_.telemetry.power_minus5v);
  response.set_power_plus2p5v(state_.telemetry.power_plus2p5v);
  response.set_power_ce(state_.telemetry.power_ce);
  response.set_temperature(state_.telemetry.temperature);
  return response;
}

daphne::telemetry::v8::ReadTelemetrySnapshotResponse
EmulatedDaphneBackend::read_telemetry_snapshot(
    const daphne::telemetry::v8::ReadTelemetrySnapshotRequest& request) const {
  daphne_sc::telemetry::SnapshotBuilder builder(request,
                                                 daphne_sc::telemetry::DetectBoardId());
  builder.CollectPlatformTelemetry();
  daphne_sc::telemetry::CollectRuntimeTelemetry(builder);
  const BoardSnapshot state = snapshot();
  const std::string base = "DAPHNE.Boards." + builder.board_id() + ".";

  builder.SetBoolean(base + "Firmware.Loaded", state.phase != BoardPhase::kPoweredOff &&
                                                   state.phase != BoardPhase::kBooting);
  builder.SetString(base + "Firmware.FpgaManagerState", "emulated");
  builder.SetString(base + "Firmware.BuildId", "daphne-emulator");
  builder.SetBoolean(base + "Firmware.ConfigurationReady",
                      state.configuration_generation != 0);
  builder.SetBoolean(base + "AFE.Global.PowerState",
                      std::any_of(state.afes.begin(), state.afes.end(),
                                  [](const AfeState& afe) { return afe.powered; }));
  builder.SetBoolean(base + "AFE.Global.ResetAsserted",
                      state.phase == BoardPhase::kResettingAfes);
  builder.SetBoolean(base + "AFE.Global.BusyAfe0", false);
  builder.SetBoolean(base + "AFE.Global.BusyAfe12", false);
  builder.SetBoolean(base + "AFE.Global.BusyAfe34", false);
  builder.SetBoolean(base + "AFE.Global.BiasEnable", state.bias_control != 0);
  builder.SetInteger(base + "AFE.Global.BiasControlCode",
                      static_cast<int32_t>(state.bias_control));

  for (uint32_t afe = 0; afe < state.afes.size(); ++afe) {
    const std::string afe_base = base + "AFE.Blocks." + std::to_string(afe) + ".";
    builder.SetInteger(afe_base + "Attenuation",
                        static_cast<int32_t>(state.afes[afe].attenuation));
    builder.SetInteger(afe_base + "VGain", static_cast<int32_t>(state.afes[afe].attenuation));
    builder.SetInteger(afe_base + "BiasSetCode", static_cast<int32_t>(state.afes[afe].bias));
    builder.SetDouble(afe_base + "BiasVoltage", state.telemetry.bias_voltage[afe]);
    builder.SetInteger(afe_base + "AlignmentDelay", static_cast<int32_t>(state.afes[afe].delay));
    builder.SetInteger(afe_base + "AlignmentBitslip",
                        static_cast<int32_t>(state.afes[afe].bitslip));
    builder.SetBoolean(afe_base + "Aligned", state.afes[afe].aligned);
  }
  for (uint32_t channel = 0; channel < state.channels.size(); ++channel) {
    const auto& source = state.channels[channel];
    const std::string channel_base = base + "Channels." + std::to_string(channel) + ".";
    builder.SetInteger(channel_base + "Trim", static_cast<int32_t>(source.trim));
    builder.SetInteger(channel_base + "Offset", static_cast<int32_t>(source.offset));
    builder.SetInteger(channel_base + "Gain", static_cast<int32_t>(source.gain));
    const bool enabled = channel < 32 ? (state.trigger_mask_low & (1u << channel)) != 0
                                      : (state.trigger_mask_high & (1u << (channel - 32))) != 0;
    builder.SetBoolean(channel_base + "TriggerEnabled", enabled);
    builder.SetInteger(channel_base + "TriggerThreshold",
                        static_cast<int32_t>(source.threshold));
    builder.SetLong(channel_base + "TriggerRecordCount",
                     static_cast<int64_t>(source.record_count));
    builder.SetLong(channel_base + "TriggerBusyCount",
                     static_cast<int64_t>(source.busy_count));
    builder.SetLong(channel_base + "TriggerFullCount",
                     static_cast<int64_t>(source.full_count));
  }
  builder.SetDouble(base + "Power.BoardRails.Minus5VA.Voltage", state.telemetry.power_minus5v);
  builder.SetDouble(base + "Power.BoardRails.3V3PDS.Voltage", state.telemetry.power_plus2p5v);
  builder.SetDouble(base + "Power.BoardRails.1V8A.Voltage", state.telemetry.power_ce);
  builder.SetString(base + "Power.BoardRails.Minus5VA.Status", "Emulated");
  builder.SetString(base + "Power.BoardRails.3V3PDS.Status", "Emulated");
  builder.SetString(base + "Power.BoardRails.1V8A.Status", "Emulated");
  builder.SetDouble(base + "Thermal.Sensors.soc.Celsius", state.telemetry.temperature);
  builder.SetString(base + "Thermal.Sensors.soc.Status", "Emulated");
  builder.SetDateTime(base + "Thermal.Sensors.soc.LastUpdate",
                       static_cast<int64_t>(daphne_sc::telemetry::UnixTimeNs()));
  builder.SetBoolean(base + "Timing.Mmcm0Locked", state.phase == BoardPhase::kReady);
  builder.SetBoolean(base + "Timing.Mmcm1Locked", state.phase == BoardPhase::kReady);
  builder.SetBoolean(base + "Timing.TimestampValid", state.phase == BoardPhase::kReady);
  builder.SetBoolean(base + "Timing.TimingUsable", state.phase == BoardPhase::kReady);
  // Current firmware replaces spy-buffer dead time with an atomic source
  // selector and inhibit. Model its backward-compatible reset state.
  builder.SetInteger(base + "Spy.Trigger.SourceSelector", 3);
  builder.SetBoolean(base + "Spy.Trigger.Inhibit", false);
  return builder.Finish();
}

BoardSnapshot EmulatedDaphneBackend::snapshot() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return state_;
}

void EmulatedDaphneBackend::set_telemetry(const TelemetryState& telemetry) {
  std::lock_guard<std::mutex> lock(mutex_);
  state_.telemetry = telemetry;
}

void EmulatedDaphneBackend::set_trigger_counters(uint32_t channel,
                                                 uint64_t record_count,
                                                 uint64_t busy_count,
                                                 uint64_t full_count) {
  if (channel >= kChannelCount) throw std::out_of_range("trigger counter channel must be 0..39");
  std::lock_guard<std::mutex> lock(mutex_);
  auto& target = state_.channels[channel];
  target.record_count = record_count;
  target.busy_count = busy_count;
  target.full_count = full_count;
}

std::chrono::nanoseconds EmulatedDaphneBackend::nominal_configure_duration(
    const daphne::ConfigureRequest& request) const {
  auto duration = std::chrono::duration_cast<std::chrono::nanoseconds>(timing_.afe_reset);
  duration += multiply_duration(timing_.afe_power_settle, 2);
  duration += multiply_duration(timing_.channel_dac_write,
                                static_cast<uint64_t>(request.channels_size()) * 2u);
  duration += multiply_duration(timing_.afe_program, static_cast<uint64_t>(request.afes_size()));
  if (timing_.auto_align) {
    duration += timing_.delayctrl_reset;
    duration += timing_.serdes_reset;
    const uint64_t snapshots = static_cast<uint64_t>(kAfeCount) *
                               (static_cast<uint64_t>(timing_.delay_taps) +
                                static_cast<uint64_t>(timing_.bitslip_taps) +
                                static_cast<uint64_t>(timing_.verification_reads));
    duration += multiply_duration(timing_.spy_snapshot, snapshots);
  }
  return duration;
}

void EmulatedDaphneBackend::sleep_for(std::chrono::nanoseconds duration) const {
  if (duration.count() <= 0 || timing_.time_scale == 0.0) return;
  const long double scaled = static_cast<long double>(duration.count()) * timing_.time_scale;
  if (scaled > static_cast<long double>(std::numeric_limits<int64_t>::max())) {
    throw std::overflow_error("scaled emulation timing duration overflow");
  }
  sleeper_(std::chrono::nanoseconds{static_cast<int64_t>(scaled)});
}

void EmulatedDaphneBackend::set_phase(BoardPhase phase) {
  std::lock_guard<std::mutex> lock(mutex_);
  state_.phase = phase;
}

daphne::ConfigureResponse EmulatedDaphneBackend::configuration_error(const std::string& message) {
  set_phase(BoardPhase::kFailed);
  daphne::ConfigureResponse response;
  response.set_success(false);
  response.set_message(message);
  return response;
}

}  // namespace daphne_sc::emulator
