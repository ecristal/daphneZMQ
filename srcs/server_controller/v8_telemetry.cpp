#include "server_controller/v8_telemetry.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <ifaddrs.h>
#include <iomanip>
#include <limits>
#include <map>
#include <mutex>
#include <net/if.h>
#include <netinet/in.h>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/statvfs.h>
#include <sys/timex.h>
#include <sys/utsname.h>
#include <unordered_map>
#include <unordered_set>
#include <unistd.h>
#include <vector>

#include <arpa/inet.h>

#ifndef DAPHNE_TELEMETRY_SCHEMA_SHA256
#define DAPHNE_TELEMETRY_SCHEMA_SHA256 "unknown"
#endif

#ifndef DAPHNE_SERVER_VERSION
#define DAPHNE_SERVER_VERSION "development"
#endif

namespace daphne_sc::telemetry {
namespace {

using daphne::telemetry::v8::DIAGNOSTIC_SEVERITY_WARNING;
using daphne::telemetry::v8::ReadTelemetrySnapshotRequest;
using daphne::telemetry::v8::ReadTelemetrySnapshotResponse;
using daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD;
using daphne::telemetry::v8::TELEMETRY_QUALITY_INVALID;
using daphne::telemetry::v8::TELEMETRY_QUALITY_NOT_APPLICABLE;
using daphne::telemetry::v8::TELEMETRY_QUALITY_UNAVAILABLE;
using daphne::telemetry::v8::TelemetryPoint;
using daphne::telemetry::v8::TelemetryQuality;

bool quality_has_value(TelemetryQuality quality) {
  return quality != TELEMETRY_QUALITY_UNAVAILABLE &&
         quality != TELEMETRY_QUALITY_NOT_APPLICABLE;
}

constexpr const char* kNodePrefix = "DAPHNE.Boards.";
constexpr const char* kBoardPlaceholder = "{BoardId}";

const CatalogEntry kCatalog[] = {
#include "server_controller/v8_telemetry_catalog.inc"
};

std::atomic<uint64_t> g_snapshot_sequence{0};

std::string trim(std::string value) {
  const auto first = value.find_first_not_of(" \t\r\n\0");
  if (first == std::string::npos) return {};
  const auto last = value.find_last_not_of(" \t\r\n\0");
  return value.substr(first, last - first + 1);
}

std::optional<std::string> read_text(const std::filesystem::path& path) {
  std::ifstream input(path);
  if (!input) return std::nullopt;
  std::ostringstream contents;
  contents << input.rdbuf();
  return trim(contents.str());
}

std::optional<int64_t> read_integer(const std::filesystem::path& path) {
  const auto value = read_text(path);
  if (!value || value->empty()) return std::nullopt;
  try {
    size_t consumed = 0;
    const auto parsed = std::stoll(*value, &consumed, 0);
    if (consumed != value->size()) return std::nullopt;
    return parsed;
  } catch (...) {
    return std::nullopt;
  }
}

std::optional<std::string> environment(const char* name) {
  const char* value = std::getenv(name);
  if (value == nullptr || *value == '\0') return std::nullopt;
  return trim(value);
}

std::string replace_board_id(std::string value, const std::string& board_id) {
  size_t offset = 0;
  while ((offset = value.find(kBoardPlaceholder, offset)) != std::string::npos) {
    value.replace(offset, std::char_traits<char>::length(kBoardPlaceholder), board_id);
    offset += board_id.size();
  }
  return value;
}

std::string board_prefix(const std::string& board_id) {
  return std::string(kNodePrefix) + board_id + ".";
}

std::optional<int64_t> parse_proc_value_kib(const std::string& key) {
  std::ifstream input("/proc/meminfo");
  std::string name;
  int64_t value = 0;
  std::string unit;
  while (input >> name >> value >> unit) {
    if (name == key + ":") return value * 1024;
  }
  return std::nullopt;
}

std::map<std::string, std::string> os_release() {
  std::map<std::string, std::string> values;
  std::ifstream input("/etc/os-release");
  std::string line;
  while (std::getline(input, line)) {
    const auto separator = line.find('=');
    if (separator == std::string::npos) continue;
    std::string value = trim(line.substr(separator + 1));
    if (value.size() >= 2 && value.front() == '"' && value.back() == '"') {
      value = value.substr(1, value.size() - 2);
    }
    values[trim(line.substr(0, separator))] = value;
  }
  return values;
}

std::map<std::string, std::string> board_configuration() {
  std::map<std::string, std::string> values;
  for (const std::filesystem::path path : {"/etc/default/firmware", "/etc/daphne-board.env"}) {
    std::ifstream input(path);
    std::string line;
    while (std::getline(input, line)) {
      line = trim(line);
      if (line.empty() || line.front() == '#') continue;
      const auto separator = line.find('=');
      if (separator == std::string::npos) continue;
      std::string value = trim(line.substr(separator + 1));
      if (value.size() >= 2 && ((value.front() == '"' && value.back() == '"') ||
                                (value.front() == '\'' && value.back() == '\''))) {
        value = value.substr(1, value.size() - 2);
      }
      values[trim(line.substr(0, separator))] = value;
    }
  }
  return values;
}

std::map<std::string, std::string> service_properties(const std::string& service) {
  struct CacheEntry {
    std::chrono::steady_clock::time_point collected_at{};
    std::map<std::string, std::string> properties;
  };
  static std::mutex cache_mutex;
  static std::map<std::string, CacheEntry> cache;
  std::lock_guard<std::mutex> cache_lock(cache_mutex);
  const auto now = std::chrono::steady_clock::now();
  const auto cached = cache.find(service);
  if (cached != cache.end() &&
      now - cached->second.collected_at < std::chrono::seconds(5)) {
    return cached->second.properties;
  }
  if (!std::all_of(service.begin(), service.end(), [](unsigned char ch) {
        return std::isalnum(ch) || ch == '.' || ch == '-' || ch == '_';
      })) {
    return {};
  }
  const std::string command =
      "systemctl show --no-pager --property=ActiveState --property=MainPID "
      "--property=NRestarts --property=ExecMainStatus " +
      service + " 2>/dev/null";
  FILE* pipe = popen(command.c_str(), "r");
  if (pipe == nullptr) return {};
  std::map<std::string, std::string> properties;
  std::array<char, 512> buffer{};
  while (fgets(buffer.data(), static_cast<int>(buffer.size()), pipe) != nullptr) {
    const std::string line = trim(buffer.data());
    const auto separator = line.find('=');
    if (separator != std::string::npos)
      properties[trim(line.substr(0, separator))] = trim(line.substr(separator + 1));
  }
  (void)pclose(pipe);
  cache[service] = CacheEntry{now, properties};
  return properties;
}

std::optional<std::pair<std::string, int32_t>> ipv4_address(const std::string& interface) {
  ifaddrs* addresses = nullptr;
  if (getifaddrs(&addresses) != 0) return std::nullopt;
  std::optional<std::pair<std::string, int32_t>> result;
  for (const ifaddrs* entry = addresses; entry != nullptr; entry = entry->ifa_next) {
    if (entry->ifa_addr == nullptr || entry->ifa_netmask == nullptr ||
        entry->ifa_addr->sa_family != AF_INET || interface != entry->ifa_name) {
      continue;
    }
    char buffer[INET_ADDRSTRLEN]{};
    const auto* address = reinterpret_cast<const sockaddr_in*>(entry->ifa_addr);
    if (inet_ntop(AF_INET, &address->sin_addr, buffer, sizeof(buffer)) == nullptr) continue;
    const auto* mask = reinterpret_cast<const sockaddr_in*>(entry->ifa_netmask);
    const uint32_t bits = ntohl(mask->sin_addr.s_addr);
    int32_t prefix = 0;
    for (uint32_t value = bits; value != 0; value <<= 1) prefix += (value & 0x80000000u) != 0;
    result = std::make_pair(std::string(buffer), prefix);
    break;
  }
  freeifaddrs(addresses);
  return result;
}

std::optional<std::string> default_gateway(const std::string& interface) {
  std::ifstream input("/proc/net/route");
  std::string line;
  std::getline(input, line);
  while (std::getline(input, line)) {
    std::istringstream row(line);
    std::string iface;
    std::string destination;
    std::string gateway;
    unsigned flags = 0;
    if (!(row >> iface >> destination >> gateway >> std::hex >> flags)) continue;
    if (iface != interface || destination != "00000000" || (flags & 0x2u) == 0) continue;
    try {
      const uint32_t raw = static_cast<uint32_t>(std::stoul(gateway, nullptr, 16));
      in_addr address{};
      address.s_addr = raw;
      char buffer[INET_ADDRSTRLEN]{};
      if (inet_ntop(AF_INET, &address, buffer, sizeof(buffer))) return std::string(buffer);
    } catch (...) {
    }
  }
  return std::nullopt;
}

std::string dns_servers() {
  std::ifstream input("/etc/resolv.conf");
  std::string line;
  std::vector<std::string> servers;
  while (std::getline(input, line)) {
    std::istringstream row(line);
    std::string key;
    std::string value;
    if (row >> key >> value && key == "nameserver") servers.push_back(value);
  }
  std::ostringstream result;
  for (size_t index = 0; index < servers.size(); ++index) {
    if (index != 0) result << ',';
    result << servers[index];
  }
  return result.str();
}

std::optional<int64_t> boot_time_ns() {
  std::ifstream input("/proc/stat");
  std::string key;
  int64_t value = 0;
  while (input >> key >> value) {
    if (key == "btime") return value * 1'000'000'000LL;
    std::string rest;
    std::getline(input, rest);
  }
  return std::nullopt;
}

}  // namespace

const CatalogEntry* catalog_begin() { return std::begin(kCatalog); }
const CatalogEntry* catalog_end() { return std::end(kCatalog); }
size_t catalog_size() { return std::size(kCatalog); }

uint64_t unix_time_ns() {
  return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                   std::chrono::system_clock::now().time_since_epoch())
                                   .count());
}

uint64_t monotonic_time_ns() {
  return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                   std::chrono::steady_clock::now().time_since_epoch())
                                   .count());
}

std::string detect_board_id() {
  if (const auto configured = environment("DAPHNE_TELEMETRY_BOARD_ID")) return *configured;
  if (const auto configured = environment("DAPHNE_BOARD_ID")) return *configured;
  std::array<char, 256> hostname{};
  if (gethostname(hostname.data(), hostname.size() - 1) == 0) {
    std::string value(hostname.data());
    std::smatch match;
    if (std::regex_search(value, match,
                          std::regex("(?:^|-)DAPHNE-([0-9]+)(?:\\.|$)",
                                     std::regex::icase))) {
      return match[1].str();
    }
    const auto dash = value.find_last_of('-');
    if (dash != std::string::npos && dash + 1 < value.size()) {
      const std::string suffix = value.substr(dash + 1);
      if (std::all_of(suffix.begin(), suffix.end(), [](unsigned char ch) { return std::isdigit(ch); }))
        return suffix;
    }
    if (!value.empty()) return value;
  }
  return "unknown";
}

class SnapshotBuilder::Impl {
 public:
  Impl(const ReadTelemetrySnapshotRequest& request, std::string board_id)
      : request_(request), board_id_(std::move(board_id)),
        snapshot_time_(unix_time_ns()), snapshot_monotonic_(monotonic_time_ns()) {
    response_.set_success(true);
    response_.set_message("DAPHNE proposed-v8 telemetry snapshot");
    response_.set_schema_major(1);
    response_.set_schema_minor(0);
    response_.set_schema_source_sha256(DAPHNE_TELEMETRY_SCHEMA_SHA256);
    response_.set_contract_revision("PDS-DAQ-ICD-proposed-v8-2026-08-17");
    response_.set_board_id(board_id_);
    response_.set_request_sequence(request.request_sequence());
    response_.set_snapshot_sequence(++g_snapshot_sequence);
    response_.set_snapshot_time_unix_ns(snapshot_time_);
    response_.set_snapshot_monotonic_ns(snapshot_monotonic_);

    timex clock_state{};
    const int clock_result = adjtimex(&clock_state);
    response_.set_wall_clock_synchronized(clock_result >= 0 &&
                                          (clock_state.status & STA_UNSYNC) == 0);

    for (const auto& requested : request.node_ids()) requested_.insert(requested);
    for (const auto& entry : kCatalog) {
      const std::string node_id = replace_board_id(entry.node_id, board_id_);
      catalog_.emplace(node_id, &entry);
    }
    for (const auto& requested : requested_) {
      if (catalog_.find(requested) == catalog_.end()) {
        add_diagnostic(DIAGNOSTIC_SEVERITY_WARNING, "request-filter", 1,
                       "Requested NodeId is not board-owned or is not in this contract: " + requested);
      }
    }
    if (request.include_unavailable()) {
      for (const auto& entry : kCatalog) {
        const std::string node_id = replace_board_id(entry.node_id, board_id_);
        if (!selected(node_id)) continue;
        TelemetryPoint* point = response_.add_points();
        initialize(*point, node_id, entry);
        point->set_quality(TELEMETRY_QUALITY_UNAVAILABLE);
        point->set_detail("No value supplied by this collector/firmware");
        points_[node_id] = response_.points_size() - 1;
      }
    }
  }

  bool selected(const std::string& node_id) const {
    return requested_.empty() || requested_.find(node_id) != requested_.end();
  }

  void initialize(TelemetryPoint& point, const std::string& node_id,
                  const CatalogEntry& entry) const {
    point.set_node_id(node_id);
    point.set_engineering_unit(entry.engineering_unit);
    point.set_source(entry.source);
    point.set_sample_time_unix_ns(snapshot_time_);
    point.set_sample_monotonic_ns(snapshot_monotonic_);
  }

  TelemetryPoint* point(const std::string& node_id, CatalogValueType expected,
                        TelemetryQuality quality, const std::string& detail) {
    if (!selected(node_id)) return nullptr;
    const auto catalog = catalog_.find(node_id);
    if (catalog == catalog_.end()) {
      add_diagnostic(DIAGNOSTIC_SEVERITY_WARNING, "collector", 2,
                     "Collector attempted unknown NodeId: " + node_id);
      return nullptr;
    }
    if (catalog->second->value_type != expected) {
      add_diagnostic(DIAGNOSTIC_SEVERITY_WARNING, "collector", 3,
                     "Collector type mismatch for NodeId: " + node_id);
      return nullptr;
    }
    TelemetryPoint* result = nullptr;
    const auto existing = points_.find(node_id);
    if (existing == points_.end()) {
      result = response_.add_points();
      initialize(*result, node_id, *catalog->second);
      points_[node_id] = response_.points_size() - 1;
    } else {
      result = response_.mutable_points(existing->second);
    }
    result->set_quality(quality);
    result->set_detail(detail);
    result->set_error_code(0);
    return result;
  }

  void add_diagnostic(daphne::telemetry::v8::DiagnosticSeverity severity,
                      const std::string& component, uint32_t code,
                      const std::string& message) {
    auto* diagnostic = response_.add_diagnostics();
    diagnostic->set_severity(severity);
    diagnostic->set_component(component);
    diagnostic->set_code(code);
    diagnostic->set_message(message);
    diagnostic->set_first_seen_time_unix_ns(snapshot_time_);
    diagnostic->set_last_seen_time_unix_ns(snapshot_time_);
    diagnostic->set_occurrence_count(1);
  }

  bool set_sample_times(const std::string& node_id, uint64_t unix_ns,
                        uint64_t monotonic_ns) {
    const auto existing = points_.find(node_id);
    if (existing == points_.end()) return false;
    TelemetryPoint* point = response_.mutable_points(existing->second);
    point->set_sample_time_unix_ns(unix_ns);
    point->set_sample_monotonic_ns(monotonic_ns);
    return true;
  }

  ReadTelemetrySnapshotRequest request_;
  std::string board_id_;
  uint64_t snapshot_time_ = 0;
  uint64_t snapshot_monotonic_ = 0;
  ReadTelemetrySnapshotResponse response_;
  std::unordered_set<std::string> requested_;
  std::unordered_map<std::string, const CatalogEntry*> catalog_;
  std::unordered_map<std::string, int> points_;
};

SnapshotBuilder::SnapshotBuilder(const ReadTelemetrySnapshotRequest& request,
                                 std::string board_id)
    : impl_(std::make_unique<Impl>(request, std::move(board_id))) {}
SnapshotBuilder::~SnapshotBuilder() = default;
SnapshotBuilder::SnapshotBuilder(SnapshotBuilder&&) noexcept = default;
SnapshotBuilder& SnapshotBuilder::operator=(SnapshotBuilder&&) noexcept = default;

const std::string& SnapshotBuilder::board_id() const { return impl_->board_id_; }
std::string SnapshotBuilder::node(const std::string& suffix) const {
  return board_prefix(impl_->board_id_) + suffix;
}

bool SnapshotBuilder::set_boolean(const std::string& id, bool value, TelemetryQuality quality,
                                  const std::string& detail) {
  auto* point = impl_->point(id, CatalogValueType::Boolean, quality, detail);
  if (!point) return false;
  if (!quality_has_value(quality)) {
    point->clear_value();
    return true;
  }
  point->set_boolean_value(value);
  return true;
}
bool SnapshotBuilder::set_integer(const std::string& id, int32_t value, TelemetryQuality quality,
                                  const std::string& detail) {
  auto* point = impl_->point(id, CatalogValueType::Integer, quality, detail);
  if (!point) return false;
  if (!quality_has_value(quality)) {
    point->clear_value();
    return true;
  }
  point->set_integer_value(value);
  return true;
}
bool SnapshotBuilder::set_long(const std::string& id, int64_t value, TelemetryQuality quality,
                               const std::string& detail) {
  auto* point = impl_->point(id, CatalogValueType::Long, quality, detail);
  if (!point) return false;
  if (!quality_has_value(quality)) {
    point->clear_value();
    return true;
  }
  point->set_long_value(value);
  return true;
}
bool SnapshotBuilder::set_double(const std::string& id, double value, TelemetryQuality quality,
                                 const std::string& detail) {
  auto* point = impl_->point(id, CatalogValueType::Double, quality, detail);
  if (!point) return false;
  if (!quality_has_value(quality)) {
    point->clear_value();
    return true;
  }
  if (!std::isfinite(value)) {
    point->set_quality(TELEMETRY_QUALITY_INVALID);
    point->set_detail("Collector returned a non-finite number");
    return false;
  }
  point->set_double_value(value);
  return true;
}
bool SnapshotBuilder::set_string(const std::string& id, const std::string& value,
                                 TelemetryQuality quality, const std::string& detail) {
  auto* point = impl_->point(id, CatalogValueType::String, quality, detail);
  if (!point) return false;
  if (!quality_has_value(quality)) {
    point->clear_value();
    return true;
  }
  point->set_string_value(value);
  return true;
}
bool SnapshotBuilder::set_datetime(const std::string& id, int64_t value,
                                   TelemetryQuality quality, const std::string& detail) {
  auto* point = impl_->point(id, CatalogValueType::DateTime, quality, detail);
  if (!point) return false;
  if (!quality_has_value(quality)) {
    point->clear_value();
    return true;
  }
  point->set_datetime_unix_ns(value);
  return true;
}

bool SnapshotBuilder::set_sample_times(const std::string& id, uint64_t unix_ns,
                                       uint64_t monotonic_ns) {
  return impl_->set_sample_times(id, unix_ns, monotonic_ns);
}

void SnapshotBuilder::add_diagnostic(daphne::telemetry::v8::DiagnosticSeverity severity,
                                     const std::string& component, uint32_t code,
                                     const std::string& message) {
  impl_->add_diagnostic(severity, component, code, message);
}

void SnapshotBuilder::collect_platform() {
  const std::string base = board_prefix(board_id());
  set_string(base + "Identity.BoardId", board_id());

  std::array<char, 256> hostname{};
  if (gethostname(hostname.data(), hostname.size() - 1) == 0) {
    set_string(base + "Identity.Hostname", hostname.data());
  }
  const std::array<std::pair<const char*, const char*>, 10> identity_environment{{
      {"DAPHNE_HWDB_ID", "Identity.HardwareDatabaseId"},
      {"DAPHNE_ASSET_TAG", "Identity.AssetTag"},
      {"DAPHNE_DETECTOR", "Identity.Detector"},
      {"DAPHNE_DETECTOR_VARIANT", "Identity.DetectorVariant"},
      {"DAPHNE_GEOGRAPHIC_LOCATION", "Identity.GeographicLocation"},
      {"DAPHNE_SOM_PRODUCT", "Identity.SomProduct"},
      {"DAPHNE_SOM_SERIAL", "Identity.SomSerial"},
      {"DAPHNE_SOM_UUID", "Identity.SomUuid"},
      {"DAPHNE_CARRIER_REVISION", "Identity.CarrierRevision"},
      {"DAPHNE_EXPECTED_HOSTNAME", "Identity.ExpectedHostname"},
  }};
  for (const auto& [name, suffix] : identity_environment) {
    if (const auto value = environment(name)) set_string(base + suffix, *value);
  }
  if (const auto expected = environment("DAPHNE_EXPECTED_HOSTNAME")) {
    set_boolean(base + "Identity.HostnameMatch", *expected == hostname.data());
  }

  const std::string interface = environment("DAPHNE_MANAGEMENT_INTERFACE").value_or("eth0");
  const std::string network = base + "Network.Interfaces." + interface + ".";
  const std::filesystem::path sys_interface = "/sys/class/net/" + interface;
  if (std::filesystem::exists(sys_interface)) {
    set_string(network + "Name", interface);
    if (const auto value = read_text(sys_interface / "address"))
      set_string(network + "MacAddress", *value);
    if (const auto value = read_text(sys_interface / "operstate"))
      set_string(network + "OperationalState", *value);
    if (const auto value = read_integer(sys_interface / "carrier"))
      set_boolean(network + "Carrier", *value != 0);
    if (const auto value = read_integer(sys_interface / "speed"))
      set_integer(network + "SpeedMbps", static_cast<int32_t>(*value));
    if (const auto value = read_text(sys_interface / "duplex"))
      set_string(network + "Duplex", *value);
    if (const auto value = read_integer(sys_interface / "mtu"))
      set_integer(network + "MtuBytes", static_cast<int32_t>(*value));
    const std::array<std::pair<const char*, const char*>, 8> statistics{{
        {"rx_bytes", "RxBytes"}, {"rx_packets", "RxPackets"},
        {"rx_errors", "RxErrors"}, {"rx_dropped", "RxDropped"},
        {"tx_bytes", "TxBytes"}, {"tx_packets", "TxPackets"},
        {"tx_errors", "TxErrors"}, {"tx_dropped", "TxDropped"},
    }};
    for (const auto& [file, suffix] : statistics) {
      if (const auto value = read_integer(sys_interface / "statistics" / file))
        set_long(network + suffix, *value);
    }
  }
  if (const auto address = ipv4_address(interface)) {
    set_string(network + "Ipv4Address", address->first);
    set_integer(network + "PrefixLength", address->second);
  }
  if (const auto gateway = default_gateway(interface))
    set_string(network + "DefaultGateway", *gateway);
  const std::string dns = dns_servers();
  if (!dns.empty()) set_string(network + "DnsServers", dns);

  const uint64_t now = unix_time_ns();
  set_datetime(base + "Host.CurrentUtc", static_cast<int64_t>(now));
  set_long(base + "Host.UnixTimeNs", static_cast<int64_t>(now));
  if (const auto uptime = read_text("/proc/uptime")) {
    try {
      set_long(base + "Host.UptimeSeconds", static_cast<int64_t>(std::stod(*uptime)));
    } catch (...) {
    }
  }
  if (const auto value = read_text("/proc/sys/kernel/random/boot_id"))
    set_string(base + "Host.BootId", *value);
  if (const auto value = boot_time_ns()) set_datetime(base + "Host.BootTime", *value);
  utsname uts{};
  if (uname(&uts) == 0) set_string(base + "Host.KernelRelease", uts.release);
  const auto release = os_release();
  const auto board_config = board_configuration();
  const auto pretty = release.find("PRETTY_NAME");
  if (pretty != release.end()) set_string(base + "Host.OperatingSystemVersion", pretty->second);
  if (const auto value = environment("DAPHNE_ROOTFS_BUILD_ID"))
    set_string(base + "Host.RootFilesystemBuildId", *value);
  if (const auto value = environment("DAPHNE_ACTIVE_BOOT_SLOT"))
    set_string(base + "Host.ActiveBootSlot", *value);
  if (const auto value = environment("DAPHNE_LAST_RESET_REASON"))
    set_string(base + "Host.LastResetReason", *value);
  timex clock_state{};
  const int clock_result = adjtimex(&clock_state);
  if (clock_result >= 0) {
    const bool synchronized = (clock_state.status & STA_UNSYNC) == 0;
    set_boolean(base + "Host.NtpSynchronized", synchronized);
    set_double(base + "Host.NtpOffsetMilliseconds",
               static_cast<double>(clock_state.offset) / 1000.0);
    set_string(base + "Host.TimeSource", synchronized ? "kernel-ntp-disciplined" : "unsynchronized");
  }
  std::array<double, 3> loads{};
  if (getloadavg(loads.data(), static_cast<int>(loads.size())) > 0)
    set_double(base + "Host.CpuLoad1Minute", loads[0]);
  if (const auto value = parse_proc_value_kib("MemAvailable"))
    set_long(base + "Host.MemoryAvailableBytes", *value);
  struct statvfs filesystem_status {};
  if (statvfs("/", &filesystem_status) == 0) {
    set_long(base + "Host.RootFilesystemFreeBytes",
             static_cast<int64_t>(filesystem_status.f_bavail) *
                 static_cast<int64_t>(filesystem_status.f_frsize));
#ifdef ST_RDONLY
    set_boolean(base + "Host.RootFilesystemReadOnly",
                (filesystem_status.f_flag & ST_RDONLY) != 0);
#endif
  }

  const std::filesystem::path fpga_state = "/sys/class/fpga_manager/fpga0/state";
  if (const auto state = read_text(fpga_state)) {
    set_string(base + "Firmware.FpgaManagerState", *state);
    set_boolean(base + "Firmware.Loaded", *state == "operating");
  }
  set_boolean(base + "Firmware.PlI2cDevicePresent",
              std::filesystem::exists("/sys/bus/platform/devices/9c000000.i2c") ||
                  std::filesystem::exists("/dev/i2c-1") ||
                  std::filesystem::exists("/dev/i2c-2"));
  set_boolean(base + "Firmware.PlSpiDevicePresent",
              std::filesystem::exists("/sys/bus/platform/devices/9c020000.axi_quad_spi") ||
                  std::filesystem::exists("/dev/spidev3.0"));
  set_boolean(base + "Firmware.FirmwarePathAvailable",
              std::filesystem::exists("/lib/firmware"));
  set_string(base + "Firmware.ServerVersion", DAPHNE_SERVER_VERSION);
  set_string(base + "Firmware.ProtobufSchemaVersion", "daphne.telemetry.v8/1.0");
  if (const auto value = environment("DAPHNE_FIRMWARE_BUILD_ID"))
    set_string(base + "Firmware.BuildId", *value);
  auto firmware_app = board_config.find("FIRMWARE_APP");
  if (firmware_app == board_config.end()) firmware_app = board_config.find("APP");
  if (firmware_app != board_config.end() && !firmware_app->second.empty()) {
    set_string(base + "Firmware.OverlayName", firmware_app->second);
    set_string(base + "Firmware.ActiveXmutilApplication", firmware_app->second);
    const auto separator = firmware_app->second.find_last_of('_');
    if (!environment("DAPHNE_FIRMWARE_BUILD_ID") &&
        separator != std::string::npos && separator + 1 < firmware_app->second.size()) {
      set_string(base + "Firmware.BuildId", firmware_app->second.substr(separator + 1));
    }
  }
  if (const auto value = environment("DAPHNE_FIRMWARE_EXPECTED_BUILD_ID")) {
    set_string(base + "Firmware.ExpectedBuildId", *value);
    if (const auto current = environment("DAPHNE_FIRMWARE_BUILD_ID"))
      set_boolean(base + "Firmware.BuildMatchesExpected", *value == *current);
  }
  if (const auto value = environment("DAPHNE_ACTIVE_XMUTIL_APPLICATION"))
    set_string(base + "Firmware.ActiveXmutilApplication", *value);

  for (const std::string bus : {"1", "2"}) {
    const std::string bus_base = base + "I2C.Buses." + bus + ".";
    const std::string path = "/dev/i2c-" + bus;
    const bool present = std::filesystem::exists(path);
    set_boolean(bus_base + "Present", present);
    set_string(bus_base + "Path", path);
    // A device node proves enumeration, not successful I2C transactions. The
    // hardware collector supplies Functional only when it has a real probe.
    set_string(bus_base + "Owner", "daphne.service");
  }
  struct I2cInventoryEntry {
    const char* bus;
    const char* address;
    const char* name;
  };
  const std::array<I2cInventoryEntry, 9> i2c_devices{{
      {"1", "0x10", "ADS7138 board/bias monitor"},
      {"1", "0x17", "ADS7138 analog-rail monitor"},
      {"2", "0x12", "PJT004A0X43 3VD3 regulator"},
      {"2", "0x16", "PJT004A0X43 2VA1 regulator"},
      {"2", "0x32", "PJT004A0X43 3VA6 regulator"},
      {"2", "0x36", "PJT004A0X43 1VD8 regulator"},
      {"2", "0x70", "Timing clock generator"},
      {"2", "0x71", "Mezzanine I2C mux/expander"},
      {"2", "0x72", "SFP I2C/GPIO expander"},
  }};
  for (const auto& device : i2c_devices) {
    const std::string bus = device.bus;
    const std::string address = device.address;
    const std::string device_base = base + "I2C.Buses." + bus + ".Devices." + address + ".";
    const unsigned numeric = static_cast<unsigned>(std::stoul(address, nullptr, 0));
    std::ostringstream sys_name;
    sys_name << bus << '-' << std::hex << std::setw(4) << std::setfill('0') << numeric;
    const std::filesystem::path sys_path = std::filesystem::path("/sys/bus/i2c/devices") / sys_name.str();
    const bool present = std::filesystem::exists(sys_path);
    set_boolean(device_base + "Present", present,
                present ? TELEMETRY_QUALITY_GOOD : TELEMETRY_QUALITY_UNAVAILABLE,
                present ? "registered in Linux sysfs" : "not enumerated; no active probe performed");
    if (const auto value = read_text(sys_path / "name"))
      set_string(device_base + "Name", *value);
    else
      set_string(device_base + "Name", device.name);
    if (present) {
      set_string(device_base + "Status", "present");
      std::error_code error;
      const auto driver = std::filesystem::read_symlink(sys_path / "driver", error);
      if (!error) set_string(device_base + "Driver", driver.filename().string());
    } else {
      set_string(device_base + "Status", "not-enumerated", TELEMETRY_QUALITY_UNAVAILABLE);
    }
  }
  const std::string spi_base = base + "SPI.spidev3.0.";
  const bool spi_present = std::filesystem::exists("/dev/spidev3.0");
  set_boolean(spi_base + "Present", spi_present);
  // Presence alone does not prove that a transfer succeeds. Leave Functional
  // unavailable until an active, non-invasive probe is implemented.
  set_string(spi_base + "Owner", "daphne.service");

  const std::array<const char*, 6> services{{
      "firmware.service", "clockchip.service", "endpoint.service", "hermes.service",
      "daphne.service", "daphne-boot-ok.service",
  }};
  for (const char* service : services) {
    const auto properties = service_properties(service);
    if (properties.empty()) continue;
    const std::string service_base = base + "Services." + service + ".";
    const auto active = properties.find("ActiveState");
    if (active != properties.end()) {
      set_string(service_base + "State", active->second);
      set_boolean(service_base + "Active", active->second == "active");
      if (std::string(service) == "daphne-boot-ok.service")
        set_boolean(base + "Host.BootMarkedGood", active->second == "active");
    }
    const auto pid = properties.find("MainPID");
    if (pid != properties.end()) {
      try {
        set_integer(service_base + "MainPid", std::stoi(pid->second));
      } catch (...) {
      }
    }
    const auto restarts = properties.find("NRestarts");
    if (restarts != properties.end()) {
      try {
        set_integer(service_base + "RestartCount", std::stoi(restarts->second));
      } catch (...) {
      }
    }
    const auto exit_status = properties.find("ExecMainStatus");
    if (exit_status != properties.end())
      set_string(service_base + "LastExitStatus", exit_status->second);
  }

  std::filesystem::path remoteproc_root = "/sys/class/remoteproc";
  std::error_code directory_error;
  bool rpu_available = false;
  if (std::filesystem::exists(remoteproc_root, directory_error)) {
    for (const auto& item : std::filesystem::directory_iterator(remoteproc_root, directory_error)) {
      const auto name = read_text(item.path() / "name");
      if (!name || (name->find("r5") == std::string::npos && name->find("R5") == std::string::npos &&
                    name->find("rpu") == std::string::npos && name->find("RPU") == std::string::npos))
        continue;
      rpu_available = true;
      if (const auto value = read_text(item.path() / "state")) {
        set_boolean(base + "RPU.Running", *value == "running");
        set_boolean(base + "Services.rpu.Active", *value == "running");
        set_string(base + "Services.rpu.State", *value);
      }
      if (const auto value = read_text(item.path() / "firmware"))
        set_string(base + "RPU.Firmware", *value);
      break;
    }
  }
  set_boolean(base + "RPU.Available", rpu_available,
              rpu_available ? TELEMETRY_QUALITY_GOOD : TELEMETRY_QUALITY_UNAVAILABLE);
}

ReadTelemetrySnapshotResponse SnapshotBuilder::finish() {
  if (!impl_->request_.include_unavailable()) {
    std::sort(impl_->response_.mutable_points()->begin(), impl_->response_.mutable_points()->end(),
              [](const TelemetryPoint& left, const TelemetryPoint& right) {
                return left.node_id() < right.node_id();
              });
  }
  return std::move(impl_->response_);
}

}  // namespace daphne_sc::telemetry
