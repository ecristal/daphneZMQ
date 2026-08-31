#include <cstdlib>
#include <functional>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "server_controller/gateware.hpp"

namespace {

class FakeMmio final : public daphne_sc::Mmio32 {
 public:
  uint32_t read32(uint64_t address) override {
    reads.push_back(address);
    const auto found = registers.find(address);
    const uint32_t value = found == registers.end() ? 0U : found->second;
    if (corrupt_read_address && address == *corrupt_read_address &&
        corrupt_reads_remaining != 0) {
      --corrupt_reads_remaining;
      return value ^ 1U;
    }
    return value;
  }

  void write32(uint64_t address, uint32_t value) override {
    writes.emplace_back(address, value);
    registers[address] = value;
  }

  std::map<uint64_t, uint32_t> registers;
  std::vector<uint64_t> reads;
  std::vector<std::pair<uint64_t, uint32_t>> writes;
  std::optional<uint64_t> corrupt_read_address;
  size_t corrupt_reads_remaining = 0;
};

void Require(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAILED: " << message << '\n';
    std::exit(1);
  }
}

void RequireThrows(const std::function<void()>& action,
                   const std::string& expected_text,
                   const std::string& message) {
  try {
    action();
  } catch (const std::exception& e) {
    Require(std::string(e.what()).find(expected_text) != std::string::npos,
            message + " (unexpected error: " + e.what() + ")");
    return;
  }
  Require(false, message + " (no exception)");
}

void TestIdentityAdmission() {
  using namespace daphne_sc;
  FakeMmio mmio;
  mmio.registers[kGatewareIdentityMagicAddress] = kGatewareIdentityMagic;
  mmio.registers[kGatewareIdentityAbiAddress] = kGatewareAbiV2;
  mmio.registers[kGatewareIdentityVariantAddress] =
      static_cast<uint32_t>(GatewareMode::kFullStream);
  mmio.registers[kGatewareIdentityBuildAddress] = 0x01234567U;

  const GatewareIdentity identity = probe_gateware_identity(mmio);
  validate_gateware_identity(identity, GatewareMode::kFullStream);
  validate_gateware_identity(identity, GatewareMode::kFullStream, 0x01234567U);
  Require(identity.build_id == 0x01234567U, "identity probe returns the build ID");
  Require(mmio.reads.size() == 4, "identity probe reads exactly four registers");
  Require(mmio.writes.empty(), "identity admission performs no writes");

  GatewareIdentity bad = identity;
  bad.magic = 0;
  RequireThrows([&] { validate_gateware_identity(bad, GatewareMode::kFullStream); },
                "magic mismatch", "bad identity magic is rejected");
  bad = identity;
  bad.abi = 0x00010000U;
  RequireThrows([&] { validate_gateware_identity(bad, GatewareMode::kFullStream); },
                "ABI mismatch", "wrong ABI is rejected");
  bad = identity;
  bad.build_id = 0x81234567U;
  RequireThrows([&] { validate_gateware_identity(bad, GatewareMode::kFullStream); },
                "non-zero upper nibble", "malformed firmware build ID is rejected");
  RequireThrows([&] { validate_gateware_identity(identity, GatewareMode::kSelfTrigger); },
                "variant mismatch", "mode mismatch is rejected");
  RequireThrows(
      [&] { validate_gateware_identity(identity, GatewareMode::kFullStream, 0x07654321U); },
      "build ID mismatch", "wrong build ID is rejected");
  Require(mmio.writes.empty(), "failed admission still performs no writes");
}

void TestModeParsing() {
  using namespace daphne_sc;
  Require(parse_gateware_mode("self-trigger") == GatewareMode::kSelfTrigger,
          "self-trigger mode parses");
  Require(parse_gateware_mode("full-stream") == GatewareMode::kFullStream,
          "full-stream mode parses");
  RequireThrows([] { (void)parse_gateware_mode("auto"); }, "Invalid gateware mode",
                "implicit auto mode is not accepted");
  Require(parse_gateware_build_id("0x09ABCDEF") == 0x09ABCDEFU,
          "hex gateware build ID parses");
  Require(parse_gateware_build_id("1234") == 1234U,
          "decimal gateware build ID parses");
  RequireThrows([] { (void)parse_gateware_build_id("0x100000000"); }, "Invalid",
                "out-of-range build ID is rejected");
  RequireThrows([] { (void)parse_gateware_build_id("0x89ABCDEF"); }, "Invalid",
                "build ID with a non-zero upper nibble is rejected");
}

void TestFullStreamPlan() {
  using namespace daphne_sc;
  Require(encode_full_stream_channel(0) == 0x00U, "channel 0 encoding");
  Require(encode_full_stream_channel(7) == 0x07U, "channel 7 encoding");
  Require(encode_full_stream_channel(8) == 0x10U, "channel 8 encoding");
  Require(encode_full_stream_channel(39) == 0x47U, "channel 39 encoding");

  const std::vector<RegisterWrite> plan = make_full_stream_mux_plan({39, 0, 8, 7});
  Require(plan.size() == kFullStreamMuxOutputCount, "mux plan always covers all 32 outputs");
  Require(plan[0].address == kFullStreamMuxBaseAddress && plan[0].value == 0x47U,
          "request order defines output zero");
  Require(plan[1].value == 0x00U && plan[2].value == 0x10U && plan[3].value == 0x07U,
          "ordered channel encodings are preserved");
  for (size_t output = 4; output < plan.size(); ++output) {
    Require(plan[output].address == kFullStreamMuxBaseAddress + output * sizeof(uint32_t),
            "mux addresses are consecutive 32-bit words");
    Require(plan[output].value == kFullStreamMuxDisabled,
            "every unused full-stream output is disabled");
  }

  for (const RegisterWrite& write : plan) {
    Require(write.address < kSelfTriggerBaseAddress ||
                write.address >= kSelfTriggerBaseAddress + 0x10000ULL,
            "full-stream plan never accesses the A001 self-trigger block");
    Require(write.address < 0x9400002CULL || write.address > 0x940000FFULL,
            "full-stream plan never writes legacy self-trigger controls");
  }

  const auto disabled = make_full_stream_mux_plan({});
  for (const RegisterWrite& write : disabled) {
    Require(write.value == kFullStreamMuxDisabled, "empty selection disables all outputs");
  }
}

void TestFullStreamValidation() {
  using namespace daphne_sc;
  std::vector<uint32_t> too_many;
  for (uint32_t channel = 0; channel < 33; ++channel) too_many.push_back(channel);
  RequireThrows([&] { (void)make_full_stream_mux_plan(too_many); }, "at most 32",
                "more than 32 outputs are rejected");
  RequireThrows([] { (void)make_full_stream_mux_plan({40}); }, "out of range",
                "invalid board channels are rejected");
  RequireThrows([] { (void)make_full_stream_mux_plan({3, 3}); }, "Duplicate",
                "duplicate board channels are rejected");
  Require(make_mode_register_plan(GatewareMode::kSelfTrigger, {}).empty(),
          "self-trigger accepts an empty full-stream selection");
  RequireThrows(
      [] { (void)make_mode_register_plan(GatewareMode::kSelfTrigger, {1}); },
      "must be empty", "self-trigger rejects full-stream channels before programming");
}

void TestFullStreamProgramming() {
  using namespace daphne_sc;
  FakeMmio mmio;
  const auto plan = make_full_stream_mux_plan({0, 8, 39});
  apply_register_plan(mmio, plan);
  Require(mmio.writes.size() == kFullStreamMuxOutputCount,
          "programming writes exactly 32 mux words");
  Require(mmio.reads.size() == kFullStreamMuxOutputCount,
          "programming verifies all 32 mux words");
  for (const auto& [address, value] : mmio.writes) {
    Require(address >= kFullStreamMuxBaseAddress &&
                address < kFullStreamMuxBaseAddress + kFullStreamMuxOutputCount * sizeof(uint32_t),
            "programming stays inside A002 mux window");
    Require(address < kSelfTriggerBaseAddress ||
                address >= kSelfTriggerBaseAddress + 0x10000ULL,
            "programming never writes A001");
    Require(address < 0x9400002CULL || address > 0x940000FFULL,
            "programming never writes aliased self-trigger controls");
    (void)value;
  }
}

void TestFullStreamSafeActivationSequence() {
  using namespace daphne_sc;
  FakeMmio mmio;
  const auto active_plan = make_full_stream_mux_plan({7, 8, 39});

  disable_full_stream_outputs(mmio);
  Require(mmio.writes.size() == kFullStreamMuxOutputCount,
          "safe sequence disables all outputs first");
  for (size_t i = 0; i < kFullStreamMuxOutputCount; ++i) {
    Require(mmio.writes[i].second == kFullStreamMuxDisabled,
            "first programming phase writes only 0xFF");
  }

  activate_full_stream_outputs(mmio, active_plan);
  Require(mmio.writes.size() == 2 * kFullStreamMuxOutputCount,
          "active plan is programmed only after the disable phase");
  Require(mmio.writes[kFullStreamMuxOutputCount].second == 0x07U &&
              mmio.writes[kFullStreamMuxOutputCount + 1].second == 0x10U &&
              mmio.writes[kFullStreamMuxOutputCount + 2].second == 0x47U,
          "activation preserves requested output order");

  FakeMmio failing_mmio;
  disable_full_stream_outputs(failing_mmio);
  failing_mmio.corrupt_read_address = kFullStreamMuxBaseAddress;
  failing_mmio.corrupt_reads_remaining = 1;
  RequireThrows(
      [&] { activate_full_stream_outputs(failing_mmio, active_plan); },
      "restored to 0xFF", "failed activation reports a successful safe rollback");
  Require(failing_mmio.writes.size() == 3 * kFullStreamMuxOutputCount,
          "failed activation is followed by a complete disable plan");
  const size_t rollback_start = 2 * kFullStreamMuxOutputCount;
  for (size_t i = rollback_start; i < failing_mmio.writes.size(); ++i) {
    Require(failing_mmio.writes[i].second == kFullStreamMuxDisabled,
            "rollback leaves every output disabled");
  }
}

void TestCounterCapability() {
  using namespace daphne_sc;
  Require(supports_trigger_counters(GatewareMode::kSelfTrigger),
          "self-trigger exposes trigger counters");
  Require(!supports_trigger_counters(GatewareMode::kFullStream),
          "full-stream does not expose trigger counters");
}

}  // namespace

int main() {
  TestIdentityAdmission();
  TestModeParsing();
  TestFullStreamPlan();
  TestFullStreamValidation();
  TestFullStreamProgramming();
  TestFullStreamSafeActivationSequence();
  TestCounterCapability();
  std::cout << "gateware mode tests passed\n";
  return 0;
}
