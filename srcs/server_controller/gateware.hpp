#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace daphne_sc {

enum class GatewareMode : uint32_t {
  kSelfTrigger = 1,
  kFullStream = 2,
};

constexpr uint64_t kGatewareIdentityMagicAddress = 0x940000F0ULL;
constexpr uint64_t kGatewareIdentityAbiAddress = 0x940000F4ULL;
constexpr uint64_t kGatewareIdentityVariantAddress = 0x940000F8ULL;
constexpr uint64_t kGatewareIdentityBuildAddress = 0x940000FCULL;
constexpr uint32_t kGatewareIdentityMagic = 0x44415048U;
constexpr uint32_t kGatewareAbiV2 = 0x00020000U;
constexpr uint32_t kGatewareBuildIdUpperNibbleMask = 0xF0000000U;

constexpr uint64_t kSelfTriggerBaseAddress = 0xA0010000ULL;
constexpr uint64_t kFullStreamMuxBaseAddress = 0xA0020000ULL;
constexpr size_t kFullStreamMuxOutputCount = 32;
constexpr uint32_t kFullStreamMuxDisabled = 0xFFU;
constexpr uint64_t kFullStreamMuxControlAddress =
    kFullStreamMuxBaseAddress + kFullStreamMuxOutputCount * sizeof(uint32_t);
constexpr uint32_t kFullStreamMuxEnableRequest = 0x1U;
constexpr uint32_t kFullStreamMuxActive = 0x2U;
constexpr size_t kFullStreamMuxWindowLength =
    kFullStreamMuxControlAddress - kFullStreamMuxBaseAddress + sizeof(uint32_t);

class Mmio32 {
 public:
  virtual ~Mmio32() = default;
  virtual uint32_t read32(uint64_t address) = 0;
  virtual void write32(uint64_t address, uint32_t value) = 0;
};

struct GatewareIdentity {
  uint32_t magic = 0;
  uint32_t abi = 0;
  uint32_t variant = 0;
  uint32_t build_id = 0;
};

struct RegisterWrite {
  uint64_t address = 0;
  uint32_t value = 0;
};

GatewareMode parse_gateware_mode(const std::string& value);
uint32_t parse_gateware_build_id(const std::string& value);
const char* gateware_mode_name(GatewareMode mode) noexcept;

GatewareIdentity probe_gateware_identity(Mmio32& mmio);
void validate_gateware_identity(
    const GatewareIdentity& identity,
    GatewareMode expected_mode,
    std::optional<uint32_t> expected_build_id = std::nullopt);

uint32_t encode_full_stream_channel(uint32_t channel);
std::vector<RegisterWrite> make_full_stream_mux_plan(const std::vector<uint32_t>& channels);
std::vector<RegisterWrite> make_mode_register_plan(GatewareMode mode,
                                                   const std::vector<uint32_t>& full_stream_channels);
void apply_register_plan(Mmio32& mmio, const std::vector<RegisterWrite>& writes);
void disable_full_stream_outputs(Mmio32& mmio);
void activate_full_stream_outputs(Mmio32& mmio,
                                  const std::vector<RegisterWrite>& active_plan);

bool supports_trigger_counters(GatewareMode mode) noexcept;

}  // namespace daphne_sc
