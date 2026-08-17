#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "emulator/EmulatedDaphneBackend.hpp"
#include "emulator/emulated_handlers.hpp"

namespace {

void require(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAILED: " << message << '\n';
    std::exit(1);
  }
}

daphne::ConfigureRequest make_request() {
  daphne::ConfigureRequest request;
  request.set_biasctrl(1300);
  request.set_self_trigger_threshold(17);

  for (const uint32_t channel_id : {0u, 39u}) {
    auto* channel = request.add_channels();
    channel->set_id(channel_id);
    channel->set_trim(channel_id + 10);
    channel->set_offset(channel_id + 20);
    channel->set_gain(1);
  }
  for (const uint32_t afe_id : {0u, 4u}) {
    auto* afe = request.add_afes();
    afe->set_id(afe_id);
    afe->set_attenuators(1600 + afe_id);
    afe->set_v_bias(100 + afe_id);
  }
  return request;
}

}  // namespace

int main() {
  using namespace std::chrono_literals;
  using daphne_sc::emulator::BoardPhase;
  using daphne_sc::emulator::EmulatedDaphneBackend;
  using daphne_sc::emulator::TimingProfile;

  std::vector<std::chrono::nanoseconds> sleeps;
  TimingProfile timing;
  timing.startup_delay = 3ms;
  timing.afe_reset = 100us;
  timing.afe_power_settle = 5ms;
  timing.channel_dac_write = 7us;
  timing.afe_program = 11us;
  timing.delayctrl_reset = 10ms;
  timing.serdes_reset = 10ms;
  timing.spy_snapshot = 1ms;
  timing.delay_taps = 2;
  timing.bitslip_taps = 1;
  timing.verification_reads = 1;

  EmulatedDaphneBackend backend(timing, [&](std::chrono::nanoseconds duration) {
    sleeps.push_back(duration);
  });
  require(backend.snapshot().phase == BoardPhase::kPoweredOff, "board starts powered off");
  backend.boot();
  require(backend.snapshot().phase == BoardPhase::kReady, "boot reaches ready");
  require(sleeps.size() == 1 && sleeps.front() == 3ms, "boot delay is scheduled");

  const auto request = make_request();
  const auto expected_duration = backend.nominal_configure_duration(request);
  const auto response = backend.configure(request);
  require(response.success(), "valid configuration succeeds");
  require(response.message().find("generation=1") != std::string::npos,
          "response includes configuration generation");

  const auto snapshot = backend.snapshot();
  require(snapshot.phase == BoardPhase::kReady, "configuration returns board to ready");
  require(snapshot.configuration_generation == 1, "generation increments");
  require(snapshot.channels[0].configured && snapshot.channels[39].configured,
          "requested channels are configured");
  require(snapshot.channels[0].threshold == 17, "threshold is retained");
  require(snapshot.afes[0].configured && snapshot.afes[4].configured,
          "requested AFEs are configured");
  require(snapshot.afes[0].aligned && snapshot.afes[4].aligned,
          "all AFEs complete alignment");
  require(snapshot.trigger_mask_low == 1u, "low trigger mask is built");
  require(snapshot.trigger_mask_high == (1u << 7), "high trigger mask is built");

  std::chrono::nanoseconds observed_configure_duration{0};
  for (size_t index = 1; index < sleeps.size(); ++index) {
    observed_configure_duration += sleeps[index];
  }
  require(observed_configure_duration == expected_duration,
          "scheduled delays match nominal configure duration");

  backend.set_trigger_counters(39, 101, 7, 2);
  daphne::ReadTriggerCountersRequest counters_request;
  counters_request.add_channels(39);
  const auto counters = backend.read_trigger_counters(counters_request);
  require(counters.success() && counters.snapshots_size() == 1, "counter read succeeds");
  require(counters.snapshots(0).record_count() == 101, "counter state is returned");
  require(backend.read_test_register().value() == 0xDEADBEEF, "test register is compatible");

  auto handlers = daphne_sc::make_emulated_v2_handlers(backend);
  std::string handler_output;
  handlers.at(daphne::MT2_CONFIGURE_FE_REQ)(request.SerializeAsString(), handler_output);
  daphne::ConfigureResponse handler_response;
  require(handler_response.ParseFromString(handler_output) && handler_response.success(),
          "protocol handler delegates to backend");
  require(backend.snapshot().configuration_generation == 2,
          "handler configuration mutates the same instance");

  daphne::ConfigureRequest invalid_request;
  invalid_request.add_channels()->set_id(40);
  const auto invalid_response = backend.configure(invalid_request);
  require(!invalid_response.success(), "invalid channel is rejected");
  require(backend.snapshot().phase == BoardPhase::kFailed, "invalid configuration records failure");

  std::cout << "emulated DAPHNE backend tests passed\n";
  return 0;
}
