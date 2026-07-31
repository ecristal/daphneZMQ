#include "server_controller/afe_delay_sweep.hpp"

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <exception>
#include <functional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "Daphne.hpp"
#include "defines.hpp"

namespace daphne_sc {
namespace {

constexpr uint32_t kAfeCount = 5;
constexpr uint32_t kChannelsPerAfe = 8;
constexpr uint32_t kMaximumDelayTap = 511;
constexpr uint32_t kRampMask = 0x3FFF;
constexpr uint64_t kMaximumCaptures = 100000;
constexpr uint32_t kMaximumSettleTimeUs = 1000000;

struct SavedAfeState {
  uint32_t board_afe = 0;
  uint32_t pl_afe = 0;
  uint32_t delay = 0;
  uint32_t bitslip = 0;
  uint32_t sync_pattern = 0;
  uint32_t test_pattern_mode = 0;
};

std::vector<uint32_t> requested_afes(
    const daphne::AfeDelaySweepRequest& request) {
  std::vector<uint32_t> afes;
  if (request.afes_size() == 0) {
    afes = {0, 1, 2, 3, 4};
    return afes;
  }

  std::set<uint32_t> seen;
  for (const uint32_t afe : request.afes()) {
    if (afe >= kAfeCount) {
      throw std::invalid_argument("AFE out of range (0..4)");
    }
    if (!seen.insert(afe).second) {
      throw std::invalid_argument("AFE list contains duplicates");
    }
    afes.push_back(afe);
  }
  return afes;
}

uint64_t point_count(const daphne::AfeDelaySweepRequest& request) {
  if (request.firsttap() > kMaximumDelayTap ||
      request.lasttap() > kMaximumDelayTap ||
      request.firsttap() > request.lasttap()) {
    throw std::invalid_argument(
        "delay tap range must satisfy 0 <= firstTap <= lastTap <= 511");
  }
  if (request.tapstep() == 0) {
    throw std::invalid_argument("tapStep must be greater than zero");
  }
  const uint32_t span = request.lasttap() - request.firsttap();
  return span / request.tapstep() + 1 +
         ((span % request.tapstep()) == 0 ? 0 : 1);
}

void validate_request(const daphne::AfeDelaySweepRequest& request,
                      size_t afe_count) {
  const uint64_t points = point_count(request);
  if (request.numberofsamples() < 2 ||
      request.numberofsamples() > 2048) {
    throw std::invalid_argument("numberOfSamples out of range (2..2048)");
  }
  if (request.numberofwaveforms() == 0) {
    throw std::invalid_argument("numberOfWaveforms must be greater than zero");
  }
  if (request.settletimeus() > kMaximumSettleTimeUs) {
    throw std::invalid_argument("settleTimeUs exceeds 1000000 us");
  }

  const uint64_t captures = points * afe_count * request.numberofwaveforms();
  if (captures > kMaximumCaptures) {
    throw std::invalid_argument(
        "delay sweep exceeds the 100000-capture safety limit");
  }
}

void append_error(std::string& errors, const std::string& error) {
  if (!errors.empty()) errors += "; ";
  errors += error;
}

std::string restore_state(Daphne& daphne,
                          const std::vector<SavedAfeState>& states,
                          uint32_t original_vtc_enable) {
  std::string errors;
  auto* front_end = daphne.getFrontEnd();
  auto* afe = daphne.getAfe();

  for (const auto& state : states) {
    try {
      front_end->setDelay(static_cast<uint8_t>(state.pl_afe), state.delay);
    } catch (const std::exception& error) {
      append_error(
          errors,
          "AFE " + std::to_string(state.board_afe) +
              " delay restore failed: " + error.what());
    } catch (...) {
      append_error(
          errors,
          "AFE " + std::to_string(state.board_afe) +
              " delay restore failed with an unknown error");
    }
  }

  // Restore the test mode before the sync bit, matching the cleanup sequence
  // used by the ramp smoke test.
  for (auto it = states.rbegin(); it != states.rend(); ++it) {
    try {
      afe->setAFEFunction(
          it->pl_afe, "TEST_PATTERN_MODES", it->test_pattern_mode);
    } catch (const std::exception& error) {
      append_error(
          errors,
          "AFE " + std::to_string(it->board_afe) +
              " test-pattern restore failed: " + error.what());
    } catch (...) {
      append_error(
          errors,
          "AFE " + std::to_string(it->board_afe) +
              " test-pattern restore failed with an unknown error");
    }
    try {
      afe->setAFEFunction(it->pl_afe, "SYNC_PATTERN", it->sync_pattern);
    } catch (const std::exception& error) {
      append_error(
          errors,
          "AFE " + std::to_string(it->board_afe) +
              " sync-pattern restore failed: " + error.what());
    } catch (...) {
      append_error(
          errors,
          "AFE " + std::to_string(it->board_afe) +
              " sync-pattern restore failed with an unknown error");
    }
  }

  try {
    front_end->setEnableDelayVtc(original_vtc_enable);
  } catch (const std::exception& error) {
    append_error(errors, std::string("VTC restore failed: ") + error.what());
  } catch (...) {
    append_error(errors, "VTC restore failed with an unknown error");
  }
  return errors;
}

}  // namespace

bool run_afe_delay_sweep(const daphne::AfeDelaySweepRequest& request,
                         daphne::AfeDelaySweepResponse& response,
                         Daphne& daphne,
                         std::string& response_str) {
  std::vector<SavedAfeState> states;
  uint32_t original_vtc_enable = 0;
  bool restore_needed = false;
  std::string operation_error;

  try {
    const std::vector<uint32_t> board_afes = requested_afes(request);
    validate_request(request, board_afes.size());

    auto* front_end = daphne.getFrontEnd();
    auto* afe = daphne.getAfe();
    auto* spy_buffer = daphne.getSpyBuffer();

    original_vtc_enable = front_end->getEnableDelayVtc();
    response.set_originalvtcenable(original_vtc_enable);

    states.reserve(board_afes.size());
    for (const uint32_t board_afe : board_afes) {
      const uint32_t pl_afe = afe_definitions::AFE_board2PL_map.at(board_afe);
      states.push_back(SavedAfeState{
          board_afe,
          pl_afe,
          front_end->getDelay(static_cast<uint8_t>(pl_afe)),
          front_end->getBitslip(static_cast<uint8_t>(pl_afe)),
          afe->getAFEFunction(pl_afe, "SYNC_PATTERN"),
          afe->getAFEFunction(pl_afe, "TEST_PATTERN_MODES"),
      });
    }

    // EN_VTC must be low while manually loading IDELAY values. Mark cleanup
    // as necessary before the write because a failed register transaction may
    // still have changed the hardware.
    restore_needed = true;
    front_end->setEnableDelayVtc(0);

    for (const auto& state : states) {
      afe->setAFEFunction(state.pl_afe, "SYNC_PATTERN", 1);
      afe->setAFEFunction(state.pl_afe, "TEST_PATTERN_MODES", 7);
    }

    const uint32_t samples = request.numberofsamples();
    const uint32_t waveforms = request.numberofwaveforms();
    const uint64_t transitions_per_channel =
        static_cast<uint64_t>(waveforms) * (samples - 1);
    std::vector<uint32_t> data(
        static_cast<size_t>(samples) * kChannelsPerAfe);
    const std::function<void()> issue_trigger =
        [front_end] { front_end->doTrigger(); };

    for (const auto& state : states) {
      auto* afe_result = response.add_afes();
      afe_result->set_afe(state.board_afe);
      afe_result->set_originaldelay(state.delay);
      afe_result->set_bitslip(state.bitslip);

      std::vector<uint32_t> mapped_channels;
      mapped_channels.reserve(kChannelsPerAfe);
      for (uint32_t lane = 0; lane < kChannelsPerAfe; ++lane) {
        mapped_channels.push_back(state.pl_afe * kChannelsPerAfe + lane);
      }

      for (uint32_t tap = request.firsttap();;) {
        front_end->setDelay(static_cast<uint8_t>(state.pl_afe), tap);
        if (request.settletimeus() != 0) {
          std::this_thread::sleep_for(
              std::chrono::microseconds(request.settletimeus()));
        }

        std::array<uint64_t, kChannelsPerAfe> failures{};
        for (uint32_t waveform = 0; waveform < waveforms; ++waveform) {
          spy_buffer->acquireFreshMappedData(
              data.data(), samples, mapped_channels, issue_trigger);

          for (uint32_t lane = 0; lane < kChannelsPerAfe; ++lane) {
            const size_t base = static_cast<size_t>(lane) * samples;
            uint32_t previous = data[base] & kRampMask;
            for (uint32_t sample = 1; sample < samples; ++sample) {
              const uint32_t current = data[base + sample] & kRampMask;
              if (((current - previous) & kRampMask) != 1) {
                ++failures[lane];
              }
              previous = current;
            }
          }
        }

        auto* point = afe_result->add_points();
        point->set_tap(tap);
        point->set_transitionsperchannel(transitions_per_channel);
        for (const uint64_t count : failures) {
          point->add_channelfailures(count);
        }

        if (tap == request.lasttap()) break;
        if (request.lasttap() - tap < request.tapstep()) {
          tap = request.lasttap();
        } else {
          tap += request.tapstep();
        }
      }
    }
  } catch (const std::exception& error) {
    operation_error = error.what();
  } catch (...) {
    operation_error = "unknown server error";
  }

  std::string restore_error;
  if (restore_needed) {
    restore_error = restore_state(daphne, states, original_vtc_enable);
  }

  if (!operation_error.empty() || !restore_error.empty()) {
    std::ostringstream message;
    if (!operation_error.empty()) {
      message << "AFE delay sweep failed: " << operation_error;
    }
    if (!restore_error.empty()) {
      if (!operation_error.empty()) message << "; ";
      message << "hardware restore failed: " << restore_error;
    }
    response_str = message.str();
    return false;
  }

  response_str = "AFE delay sweep completed and original hardware state restored";
  return true;
}

}  // namespace daphne_sc
