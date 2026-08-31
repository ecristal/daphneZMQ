#include "server_controller/gateware.hpp"

#include <array>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>

namespace daphne_sc {
namespace {

std::string hex32(uint32_t value) {
  std::ostringstream out;
  out << "0x" << std::hex << std::uppercase << std::setw(8) << std::setfill('0') << value;
  return out.str();
}

}  // namespace

GatewareMode parse_gateware_mode(const std::string& value) {
  if (value == "self-trigger") return GatewareMode::kSelfTrigger;
  if (value == "full-stream") return GatewareMode::kFullStream;
  throw std::invalid_argument(
      "Invalid gateware mode '" + value + "' (expected self-trigger or full-stream)");
}

uint32_t parse_gateware_build_id(const std::string& value) {
  if (value.empty()) throw std::invalid_argument("Gateware build ID must not be empty");
  size_t parsed = 0;
  unsigned long long build_id = 0;
  try {
    build_id = std::stoull(value, &parsed, 0);
  } catch (const std::exception&) {
    throw std::invalid_argument("Invalid gateware build ID '" + value + "'");
  }
  if (parsed != value.size() || build_id > std::numeric_limits<uint32_t>::max() ||
      (build_id & kGatewareBuildIdUpperNibbleMask) != 0) {
    throw std::invalid_argument("Invalid gateware build ID '" + value + "'");
  }
  return static_cast<uint32_t>(build_id);
}

const char* gateware_mode_name(GatewareMode mode) noexcept {
  switch (mode) {
    case GatewareMode::kSelfTrigger:
      return "self-trigger";
    case GatewareMode::kFullStream:
      return "full-stream";
  }
  return "unknown";
}

GatewareIdentity probe_gateware_identity(Mmio32& mmio) {
  GatewareIdentity identity;
  identity.magic = mmio.read32(kGatewareIdentityMagicAddress);
  identity.abi = mmio.read32(kGatewareIdentityAbiAddress);
  identity.variant = mmio.read32(kGatewareIdentityVariantAddress);
  identity.build_id = mmio.read32(kGatewareIdentityBuildAddress);
  return identity;
}

void validate_gateware_identity(const GatewareIdentity& identity,
                                GatewareMode expected_mode,
                                std::optional<uint32_t> expected_build_id) {
  if (identity.magic != kGatewareIdentityMagic) {
    throw std::runtime_error("Gateware identity magic mismatch: expected " +
                             hex32(kGatewareIdentityMagic) + ", read " +
                             hex32(identity.magic));
  }
  if (identity.abi != kGatewareAbiV2) {
    throw std::runtime_error("Gateware register ABI mismatch: expected " +
                             hex32(kGatewareAbiV2) + ", read " + hex32(identity.abi));
  }
  if ((identity.build_id & kGatewareBuildIdUpperNibbleMask) != 0) {
    throw std::runtime_error(
        "Gateware build ID has a non-zero upper nibble; ABI v2 requires the "
        "zero-extended first seven commit-SHA hex characters: read " +
        hex32(identity.build_id));
  }
  if (expected_build_id &&
      (*expected_build_id & kGatewareBuildIdUpperNibbleMask) != 0) {
    throw std::invalid_argument(
        "Expected gateware build ID has a non-zero upper nibble; ABI v2 "
        "requires the zero-extended first seven commit-SHA hex characters");
  }
  const uint32_t expected_variant = static_cast<uint32_t>(expected_mode);
  if (identity.variant != expected_variant) {
    throw std::runtime_error("Gateware variant mismatch: requested " +
                             std::string(gateware_mode_name(expected_mode)) + " (" +
                             hex32(expected_variant) + "), read " + hex32(identity.variant));
  }
  if (expected_build_id && identity.build_id != *expected_build_id) {
    throw std::runtime_error("Gateware build ID mismatch: expected " +
                             hex32(*expected_build_id) + ", read " +
                             hex32(identity.build_id));
  }
}

uint32_t encode_full_stream_channel(uint32_t channel) {
  if (channel >= 40) {
    throw std::invalid_argument("Full-stream channel out of range (0..39): " +
                                std::to_string(channel));
  }
  return ((channel / 8U) << 4U) | (channel % 8U);
}

std::vector<RegisterWrite> make_full_stream_mux_plan(const std::vector<uint32_t>& channels) {
  if (channels.size() > kFullStreamMuxOutputCount) {
    throw std::invalid_argument("Full-stream configuration has " +
                                std::to_string(channels.size()) +
                                " channels; at most 32 outputs are available");
  }

  std::array<bool, 40> seen{};
  for (const uint32_t channel : channels) {
    if (channel >= seen.size()) {
      throw std::invalid_argument("Full-stream channel out of range (0..39): " +
                                  std::to_string(channel));
    }
    if (seen[channel]) {
      throw std::invalid_argument("Duplicate full-stream channel: " +
                                  std::to_string(channel));
    }
    seen[channel] = true;
  }

  std::vector<RegisterWrite> writes;
  writes.reserve(kFullStreamMuxOutputCount);
  for (size_t output = 0; output < kFullStreamMuxOutputCount; ++output) {
    const uint32_t value = output < channels.size()
                               ? encode_full_stream_channel(channels[output])
                               : kFullStreamMuxDisabled;
    writes.push_back({kFullStreamMuxBaseAddress + output * sizeof(uint32_t), value});
  }
  return writes;
}

std::vector<RegisterWrite> make_mode_register_plan(
    GatewareMode mode,
    const std::vector<uint32_t>& full_stream_channels) {
  if (mode == GatewareMode::kSelfTrigger) {
    if (!full_stream_channels.empty()) {
      throw std::invalid_argument(
          "full_stream_channels must be empty in self-trigger gateware mode");
    }
    return {};
  }
  return make_full_stream_mux_plan(full_stream_channels);
}

void apply_register_plan(Mmio32& mmio, const std::vector<RegisterWrite>& writes) {
  for (const RegisterWrite& write : writes) {
    mmio.write32(write.address, write.value);
  }
  for (const RegisterWrite& write : writes) {
    const uint32_t readback = mmio.read32(write.address) & 0xFFU;
    if (readback != write.value) {
      throw std::runtime_error("MMIO readback mismatch at " +
                               hex32(static_cast<uint32_t>(write.address)) + ": wrote " +
                               hex32(write.value) + ", read " + hex32(readback));
    }
  }
}

void disable_full_stream_outputs(Mmio32& mmio) {
  apply_register_plan(mmio, make_full_stream_mux_plan({}));
}

void activate_full_stream_outputs(Mmio32& mmio,
                                  const std::vector<RegisterWrite>& active_plan) {
  try {
    apply_register_plan(mmio, active_plan);
  } catch (const std::exception& activation_error) {
    try {
      disable_full_stream_outputs(mmio);
    } catch (const std::exception& disable_error) {
      throw std::runtime_error(
          std::string("Full-stream mux activation failed: ") + activation_error.what() +
          "; restoring all outputs to 0xFF also failed: " + disable_error.what());
    }
    throw std::runtime_error(std::string("Full-stream mux activation failed: ") +
                             activation_error.what() +
                             "; all outputs were restored to 0xFF");
  }
}

bool supports_trigger_counters(GatewareMode mode) noexcept {
  return mode == GatewareMode::kSelfTrigger;
}

}  // namespace daphne_sc
