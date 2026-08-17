#include "server_controller/v8_hardware_telemetry.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

#include "Daphne.hpp"
#include "DevMem.hpp"
#include "defines.hpp"
#include "server_controller/v8_telemetry.hpp"
#include "server_controller/v8_telemetry_runtime.hpp"

namespace daphne_sc::telemetry {
namespace {

using daphne::telemetry::v8::DIAGNOSTIC_SEVERITY_WARNING;
using daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD;
using daphne::telemetry::v8::TELEMETRY_QUALITY_INVALID;
using daphne::telemetry::v8::TELEMETRY_QUALITY_STALE;
using daphne::telemetry::v8::TelemetryQuality;

constexpr uint64_t kCachedMonitorStaleAfterNs = 5'000'000'000ULL;

struct CachedSample {
  TelemetryQuality quality = TELEMETRY_QUALITY_STALE;
  std::string detail;
  uint64_t unix_ns = 0;
  uint64_t monotonic_ns = 0;
};

CachedSample cached_sample(uint64_t unix_ns, uint64_t monotonic_ns) {
  CachedSample sample;
  sample.unix_ns = unix_ns;
  sample.monotonic_ns = monotonic_ns;
  const uint64_t now = monotonic_time_ns();
  if (unix_ns == 0 || monotonic_ns == 0 || monotonic_ns > now) {
    sample.quality = TELEMETRY_QUALITY_STALE;
    sample.detail = "Cached monitor timestamp is unavailable or invalid";
    return sample;
  }
  const uint64_t age_ns = now - monotonic_ns;
  if (age_ns <= kCachedMonitorStaleAfterNs) {
    sample.quality = TELEMETRY_QUALITY_GOOD;
    return sample;
  }
  sample.quality = TELEMETRY_QUALITY_STALE;
  sample.detail = "Cached monitor sample is " +
                  std::to_string(age_ns / 1'000'000ULL) + " ms old";
  return sample;
}

uint32_t read_mmio(uint64_t address) {
  DevMem memory(address);
  memory.map_memory(sizeof(uint32_t));
  return memory.read_u32(0);
}

uint64_t read_counter64(DevMem& memory, size_t low_offset, size_t high_offset) {
  for (unsigned attempt = 0; attempt < 3; ++attempt) {
    const uint32_t high_before = memory.read_u32(high_offset);
    const uint32_t low = memory.read_u32(low_offset);
    const uint32_t high_after = memory.read_u32(high_offset);
    if (high_before == high_after)
      return (static_cast<uint64_t>(high_after) << 32) | low;
  }
  const uint32_t high = memory.read_u32(high_offset);
  const uint32_t low = memory.read_u32(low_offset);
  return (static_cast<uint64_t>(high) << 32) | low;
}

std::string hex_value(uint64_t value, unsigned width) {
  std::ostringstream output;
  output << "0x" << std::uppercase << std::hex << std::setw(static_cast<int>(width))
         << std::setfill('0') << value;
  return output.str();
}

std::string endpoint_state(uint32_t state) {
  switch (state) {
    case 0: return "Reset";
    case 1: return "WaitClock";
    case 2: return "WaitTimestamp";
    case 3: return "Training";
    case 4: return "Aligning";
    case 5: return "Synchronizing";
    case 6: return "OperationalPending";
    case 7: return "Recovering";
    case 8: return "Ready";
    default: return "Unknown(" + std::to_string(state) + ")";
  }
}

template <typename Function>
void guarded(SnapshotBuilder& builder, const std::string& component, Function&& function) {
  try {
    function();
  } catch (const std::exception& error) {
    builder.add_diagnostic(DIAGNOSTIC_SEVERITY_WARNING, component, 1, error.what());
  }
}

std::optional<double> thermal_zone(const std::string& requested_name) {
  std::error_code error;
  const std::filesystem::path root = "/sys/class/thermal";
  if (!std::filesystem::exists(root, error)) return std::nullopt;
  std::optional<double> fallback;
  for (const auto& item : std::filesystem::directory_iterator(root, error)) {
    if (error || item.path().filename().string().rfind("thermal_zone", 0) != 0) continue;
    std::ifstream type_file(item.path() / "type");
    std::ifstream temp_file(item.path() / "temp");
    std::string type;
    double milli_celsius = 0.0;
    if (!std::getline(type_file, type) || !(temp_file >> milli_celsius)) continue;
    const double celsius = std::abs(milli_celsius) > 1000.0 ? milli_celsius / 1000.0
                                                            : milli_celsius;
    if (!fallback) fallback = celsius;
    std::string lower = type;
    std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char value) {
      return static_cast<char>(std::tolower(value));
    });
    if (lower.find(requested_name) != std::string::npos) return celsius;
    if (requested_name == "soc" && (lower.find("cpu") != std::string::npos ||
                                     lower.find("xilinx") != std::string::npos))
      return celsius;
  }
  return requested_name == "soc" ? fallback : std::nullopt;
}

}  // namespace

daphne::telemetry::v8::ReadTelemetrySnapshotResponse collect_hardware_snapshot(
    const daphne::telemetry::v8::ReadTelemetrySnapshotRequest& request,
    Daphne& daphne) {
  SnapshotBuilder builder(request, detect_board_id());
  builder.collect_platform();
  collect_runtime(builder);
  const std::string base = "DAPHNE.Boards." + builder.board_id() + ".";

  if (!daphne.peripheralsInitialized()) {
    builder.add_diagnostic(
        DIAGNOSTIC_SEVERITY_WARNING, "hardware-peripherals", 2,
        "Telemetry-only mode: I2C/SPI peripheral initialization and live bus reads are disabled");
  }

  builder.set_boolean(base + "I2C.Buses.1.Busy", daphne.isI2C_1_device_configuring.load());
  builder.set_boolean(base + "I2C.Buses.2.Busy", daphne.isI2C_2_device_configuring.load());

  if (daphne.peripheralsInitialized()) {
    const bool i2c1_functional = daphne.getADS7138_Driver_addr_0x10() != nullptr &&
                                 daphne.getADS7138_Driver_addr_0x17() != nullptr;
    builder.set_boolean(
        base + "I2C.Buses.1.Functional", i2c1_functional,
        i2c1_functional ? TELEMETRY_QUALITY_GOOD : TELEMETRY_QUALITY_INVALID,
        i2c1_functional ? "Peripheral initialization succeeded"
                        : "One or more required ADS7138 drivers failed initialization");
    const bool i2c2_functional = daphne.getHDMezzDriver() != nullptr &&
                                 daphne.getRegulatorsDriver() != nullptr;
    builder.set_boolean(
        base + "I2C.Buses.2.Functional", i2c2_functional,
        i2c2_functional ? TELEMETRY_QUALITY_GOOD : TELEMETRY_QUALITY_INVALID,
        i2c2_functional ? "Peripheral initialization succeeded"
                        : "One or more required I2C-2 drivers failed initialization");
    const bool spi_functional = daphne.getCurrentMonitorDriver() != nullptr;
    builder.set_boolean(
        base + "SPI.spidev3.0.Functional", spi_functional,
        spi_functional ? TELEMETRY_QUALITY_GOOD : TELEMETRY_QUALITY_INVALID,
        spi_functional ? "Current-monitor initialization succeeded"
                       : "Current-monitor SPI initialization failed");
  }

  if (daphne.board_rail_monitor_valid.load()) {
    const CachedSample sample = cached_sample(
        daphne.board_rail_last_success_unix_ns.load(),
        daphne.board_rail_last_success_monotonic_ns.load());
    const auto set_cached_double = [&](const std::string& node_id, double value) {
      builder.set_double(node_id, value, sample.quality, sample.detail);
      builder.set_sample_times(node_id, sample.unix_ns, sample.monotonic_ns);
    };
    const auto set_cached_string = [&](const std::string& node_id,
                                       const std::string& value) {
      builder.set_string(node_id, value, sample.quality, sample.detail);
      builder.set_sample_times(node_id, sample.unix_ns, sample.monotonic_ns);
    };
    const std::array<std::pair<const char*, const std::atomic<double>*>, 5> rails{{
        {"3V3PDS", &daphne._3V3PDS_voltage},
        {"1V8PDS", &daphne._1V8PDS_voltage},
        {"3V3A", &daphne._3V3A_voltage},
        {"1V8A", &daphne._1V8A_voltage},
        {"Minus5VA", &daphne._n5VA_voltage},
    }};
    for (const auto& [name, value] : rails) {
      set_cached_double(base + "Power.BoardRails." + name + ".Voltage", value->load());
      set_cached_string(base + "Power.BoardRails." + name + ".Status",
                        sample.quality == TELEMETRY_QUALITY_GOOD
                            ? "ReadbackValid"
                            : "ReadbackStale");
    }
    const std::array<const std::atomic<double>*, 5> biases{{
        &daphne._VBIAS_0_voltage, &daphne._VBIAS_1_voltage, &daphne._VBIAS_2_voltage,
        &daphne._VBIAS_3_voltage, &daphne._VBIAS_4_voltage,
    }};
    for (size_t afe = 0; afe < biases.size(); ++afe) {
      set_cached_double(base + "AFE.Blocks." + std::to_string(afe) + ".BiasVoltage",
                        biases[afe]->load());
    }
  }

  if (auto* hd = daphne.getHDMezzDriver()) {
    for (uint32_t afe = 0; afe < 5; ++afe) {
      const std::string hd_base = base + "HDMezz." + std::to_string(afe) + ".";
      const bool enabled = hd->isAfeBlockEnabled(static_cast<uint8_t>(afe));
      const bool configured = hd->isAfeBlockConfigured(static_cast<uint8_t>(afe));
      builder.set_boolean(hd_base + "BlockEnabled", enabled);
      builder.set_boolean(hd_base + "Configured", configured);
      if (configured) {
        builder.set_double(hd_base + "RShunt5V", hd->getRShunt(afe, "5V"));
        builder.set_double(hd_base + "RShunt3V3", hd->getRShunt(afe, "3V3"));
        builder.set_double(hd_base + "MaxCurrentScale5V", hd->getMaxCurrentScale(afe, "5V"));
        builder.set_double(hd_base + "MaxCurrentScale3V3", hd->getMaxCurrentScale(afe, "3V3"));
        builder.set_double(hd_base + "ShutdownCurrent5V", hd->getMaxCurrentShutdown(afe, "5V"));
        builder.set_double(hd_base + "ShutdownCurrent3V3", hd->getMaxCurrentShutdown(afe, "3V3"));
        builder.set_double(hd_base + "MaxPower5V", hd->getMaxPower(afe, "5V"));
        builder.set_double(hd_base + "MaxPower3V3", hd->getMaxPower(afe, "3V3"));
        builder.set_double(hd_base + "CurrentLsb5V", hd->getCurrentLsb(afe, "5V"));
        builder.set_double(hd_base + "CurrentLsb3V3", hd->getCurrentLsb(afe, "3V3"));
        builder.set_integer(hd_base + "ShuntCal5V", hd->getShuntCal(afe, "5V"));
        builder.set_integer(hd_base + "ShuntCal3V3", hd->getShuntCal(afe, "3V3"));
      }
      if (daphne.HDMezz_monitor_valid[afe].load()) {
        const CachedSample sample = cached_sample(
            daphne.HDMezz_last_success_unix_ns[afe].load(),
            daphne.HDMezz_last_success_monotonic_ns[afe].load());
        const auto set_cached_boolean = [&](const std::string& node_id, bool value) {
          builder.set_boolean(node_id, value, sample.quality, sample.detail);
          builder.set_sample_times(node_id, sample.unix_ns, sample.monotonic_ns);
        };
        const auto set_cached_double = [&](const std::string& node_id, double value) {
          builder.set_double(node_id, value, sample.quality, sample.detail);
          builder.set_sample_times(node_id, sample.unix_ns, sample.monotonic_ns);
        };
        set_cached_boolean(hd_base + "Power5VRequested",
                           daphne.HDMezz_5V_is_powered[afe].load());
        set_cached_boolean(hd_base + "Power3V3Requested",
                           daphne.HDMezz_3V3_is_powered[afe].load());
        set_cached_double(hd_base + "Voltage5V", daphne.HDMezz_5V_voltage[afe].load());
        set_cached_double(hd_base + "Current5V", daphne.HDMezz_5V_current[afe].load());
        set_cached_double(hd_base + "Power5V", daphne.HDMezz_5V_power[afe].load());
        set_cached_boolean(hd_base + "Alert5V", daphne.HDMezz_5V_alert[afe].load());
        set_cached_double(hd_base + "Voltage3V3", daphne.HDMezz_3V3_voltage[afe].load());
        set_cached_double(hd_base + "Current3V3", daphne.HDMezz_3V3_current[afe].load());
        set_cached_double(hd_base + "Power3V3", daphne.HDMezz_3V3_power[afe].load());
        set_cached_boolean(hd_base + "Alert3V3", daphne.HDMezz_3V3_alert[afe].load());
      }
    }
  }

  if (auto* regulators = daphne.getRegulatorsDriver()) {
    std::unique_lock<std::mutex> lock(daphne.i2c_2_mutex, std::try_to_lock);
    if (lock.owns_lock()) {
      const std::array<const char*, 4> names{{"3VD3", "2VA1", "3VA6", "1VD8"}};
      for (uint8_t rail = 0; rail < names.size(); ++rail) {
        guarded(builder, std::string("pmbus-") + names[rail], [&] {
          const double voltage = regulators->readRailVoltage(rail);
          const double current = regulators->readRailCurrent(rail);
          const double temperature = regulators->readTemperature(rail);
          const std::string rail_base = base + "Power.PMBus." + names[rail] + ".";
          builder.set_double(rail_base + "Voltage", voltage);
          builder.set_double(rail_base + "Current", current);
          builder.set_double(rail_base + "Power", voltage * current);
          builder.set_double(rail_base + "Temperature", temperature);
          builder.set_string(rail_base + "Health", "ReadbackValid");
        });
      }
    }
  }

  guarded(builder, "board-registers", [&] {
    const uint32_t afe_global = read_mmio(0x80000000ULL);
    builder.set_boolean(base + "AFE.Global.ResetAsserted", (afe_global & 0x1u) != 0);
    builder.set_boolean(base + "AFE.Global.PowerState", (afe_global & 0x2u) != 0);
    builder.set_boolean(base + "AFE.Global.BusyAfe0", (afe_global & 0x4u) != 0);
    builder.set_boolean(base + "AFE.Global.BusyAfe12", (afe_global & 0x8u) != 0);
    builder.set_boolean(base + "AFE.Global.BusyAfe34", (afe_global & 0x10u) != 0);

    const uint32_t clock_control = read_mmio(0x84000000ULL);
    const uint32_t clock_status = read_mmio(0x84000004ULL);
    const uint32_t endpoint_control = read_mmio(0x84000008ULL);
    const uint32_t endpoint_status = read_mmio(0x8400000CULL);
    const uint32_t fsm = endpoint_status & 0xFu;
    const bool timestamp_ok = (endpoint_status & 0x10u) != 0;
    builder.set_boolean(base + "Timing.ClockSourceControlled", (clock_control & 0x4u) != 0);
    builder.set_boolean(base + "Timing.Mmcm0Locked", (clock_status & 0x1u) != 0);
    builder.set_boolean(base + "Timing.Mmcm1Locked", (clock_status & 0x2u) != 0);
    builder.set_string(base + "Timing.EndpointFsmState", endpoint_state(fsm));
    builder.set_integer(base + "Timing.EndpointFsmRaw", static_cast<int32_t>(fsm));
    builder.set_boolean(base + "Timing.TimestampValid", timestamp_ok);
    builder.set_boolean(base + "Timing.TimingUsable", fsm == 8 && timestamp_ok &&
                                                      (clock_status & 0x3u) == 0x3u);
    builder.set_integer(base + "Timing.RawEndpointStatus", static_cast<int32_t>(endpoint_status));
    builder.set_integer(base + "Timing.EndpointAddress", static_cast<int32_t>(endpoint_control & 0xFFFFu));
    builder.set_integer(base + "Identity.TimingEndpointAddress",
                        static_cast<int32_t>(endpoint_control & 0xFFFFu));

    const uint64_t timestamp =
        static_cast<uint64_t>(read_mmio(0x9002D000ULL) & 0xFFFFu) |
        (static_cast<uint64_t>(read_mmio(0x9002E000ULL) & 0xFFFFu) << 16) |
        (static_cast<uint64_t>(read_mmio(0x9002F000ULL) & 0xFFFFu) << 32) |
        (static_cast<uint64_t>(read_mmio(0x90030000ULL) & 0xFFFFu) << 48);
    builder.set_long(base + "Timing.Timestamp", static_cast<int64_t>(timestamp));

    const uint32_t frontend_status = read_mmio(0x88000004ULL);
    const uint32_t spy_trigger_control = read_mmio(0x88000034ULL);
    builder.set_integer(base + "Spy.Trigger.SourceSelector",
                        static_cast<int32_t>(spy_trigger_control & 0x3u));
    builder.set_boolean(base + "Spy.Trigger.Inhibit", (spy_trigger_control & 0x4u) != 0);
    for (uint32_t afe = 0; afe < 5; ++afe) {
      const std::string afe_base = base + "AFE.Blocks." + std::to_string(afe) + ".";
      builder.set_integer(afe_base + "AlignmentDelay",
                          static_cast<int32_t>(read_mmio(0x8800000CULL + afe * 4) & 0x1FFu));
      builder.set_integer(afe_base + "AlignmentBitslip",
                          static_cast<int32_t>(read_mmio(0x88000020ULL + afe * 4) & 0xFu));
      if ((frontend_status & 0x1u) == 0)
        builder.set_boolean(afe_base + "Aligned", false,
                            daphne::telemetry::v8::TELEMETRY_QUALITY_INVALID,
                            "Delay controller is not ready");
    }

    const uint32_t fan_control = read_mmio(0x94000000ULL) & 0xFFu;
    for (uint32_t fan = 0; fan < 2; ++fan) {
      const uint32_t tach = read_mmio(0x94000004ULL + fan * 4) & 0xFFFu;
      const std::string fan_base = base + "Thermal.Fans." + std::to_string(fan) + ".";
      builder.set_boolean(fan_base + "Present", true);
      builder.set_integer(fan_base + "PwmCommand", static_cast<int32_t>(fan_control));
      builder.set_integer(fan_base + "TachometerRaw", static_cast<int32_t>(tach));
      builder.set_boolean(fan_base + "Running", tach != 0);
      builder.set_boolean(fan_base + "Stalled", fan_control != 0 && tach == 0);
      builder.set_string(fan_base + "ControlMode", "SharedManualPwm");
      builder.set_datetime(fan_base + "LastUpdate", static_cast<int64_t>(unix_time_ns()));
    }
    builder.set_boolean(base + "AFE.Global.BiasEnable", (read_mmio(0x9400000CULL) & 0x1u) != 0);
    const uint32_t git = read_mmio(0x9400001CULL) & 0x0FFFFFFFu;
    builder.set_string(base + "Firmware.GitCommit", hex_value(git, 7));
    builder.set_integer(base + "Identity.LinkId", static_cast<int32_t>(read_mmio(0x94000028ULL) & 0x3Fu));
    builder.set_integer(base + "Identity.SlotId", static_cast<int32_t>(read_mmio(0x9400002CULL) & 0xFu));
    builder.set_integer(base + "Identity.CrateId", static_cast<int32_t>(read_mmio(0x94000030ULL) & 0x3FFu));
    builder.set_integer(base + "Identity.DetectorId", static_cast<int32_t>(read_mmio(0x94000034ULL) & 0x3Fu));
    builder.set_integer(base + "Identity.RegisterMapVersion", static_cast<int32_t>(read_mmio(0x94000038ULL) & 0x3Fu));
    builder.add_diagnostic(
        DIAGNOSTIC_SEVERITY_WARNING, "register-map", 3,
        "Self-trigger config/delay/filter readback is withheld: the proposed addresses "
        "overlap idSlot/idCrate/idDetector in this firmware register map");
  });

  guarded(builder, "trigger-registers", [&] {
    const uint32_t mask_low = read_mmio(0x94000020ULL);
    const uint32_t mask_high = read_mmio(0x94000024ULL);
    DevMem counters(0xA0010000ULL);
    constexpr size_t kStride = 0x20;
    counters.map_memory(40 * kStride);
    for (uint32_t channel = 0; channel < 40; ++channel) {
      const size_t offset = channel * kStride;
      const std::string channel_base = base + "Channels." + std::to_string(channel) + ".";
      const bool enabled = channel < 32 ? (mask_low & (1u << channel)) != 0
                                        : (mask_high & (1u << (channel - 32))) != 0;
      builder.set_boolean(channel_base + "TriggerEnabled", enabled);
      builder.set_integer(channel_base + "TriggerThreshold",
                          static_cast<int32_t>(counters.read_u32(offset) & 0x0FFFFFFFu));
      builder.set_long(channel_base + "TriggerRecordCount",
                       static_cast<int64_t>(read_counter64(counters, offset + 0x04, offset + 0x08)));
      builder.set_long(channel_base + "TriggerBusyCount",
                       static_cast<int64_t>(read_counter64(counters, offset + 0x0C, offset + 0x10)));
      builder.set_long(channel_base + "TriggerFullCount",
                       static_cast<int64_t>(read_counter64(counters, offset + 0x14, offset + 0x18)));
    }
  });

  for (const std::string sensor : {"soc", "carrier"}) {
    if (const auto temperature = thermal_zone(sensor)) {
      const std::string thermal = base + "Thermal.Sensors." + sensor + ".";
      builder.set_double(thermal + "Celsius", *temperature);
      builder.set_string(thermal + "Status", "ReadbackValid");
      builder.set_datetime(thermal + "LastUpdate", static_cast<int64_t>(unix_time_ns()));
    }
  }

  return builder.finish();
}

}  // namespace daphne_sc::telemetry
