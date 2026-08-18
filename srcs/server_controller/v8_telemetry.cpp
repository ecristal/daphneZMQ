#include "server_controller/v8_telemetry.hpp"

#include <arpa/inet.h>
#include <google/protobuf/descriptor.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <sys/statvfs.h>
#include <sys/timex.h>
#include <sys/utsname.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <mutex>
#include <optional>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

#ifndef DAPHNE_TELEMETRY_SCHEMA_SHA256
#error "DAPHNE_TELEMETRY_SCHEMA_SHA256 must identify the compiled telemetry schema"
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
using daphne::telemetry::v8::TelemetryQuality;

bool QualityHasValue(TelemetryQuality quality) {
  return quality != TELEMETRY_QUALITY_UNAVAILABLE && quality != TELEMETRY_QUALITY_NOT_APPLICABLE;
}

constexpr const char* kNodePrefix = "DAPHNE.Boards.";
constexpr const char* kBoardPlaceholder = "{BoardId}";

const CatalogEntry kCatalog[] = {
#include "server_controller/v8_telemetry_catalog.inc"
};

std::atomic<uint64_t> g_snapshot_sequence{0};

std::string Trim(std::string value) {
  const auto first = value.find_first_not_of(" \t\r\n\0");
  if (first == std::string::npos) return {};
  const auto last = value.find_last_not_of(" \t\r\n\0");
  return value.substr(first, last - first + 1);
}

std::optional<std::string> ReadText(const std::filesystem::path& path) {
  std::ifstream input(path);
  if (!input) return std::nullopt;
  std::ostringstream contents;
  contents << input.rdbuf();
  return Trim(contents.str());
}

std::optional<int64_t> ReadInteger(const std::filesystem::path& path) {
  const auto value = ReadText(path);
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

std::optional<std::string> GetEnvironment(const char* name) {
  const char* value = std::getenv(name);
  if (value == nullptr || *value == '\0') return std::nullopt;
  return Trim(value);
}

std::string ReplaceBoardId(std::string value, const std::string& board_id) {
  size_t offset = 0;
  while ((offset = value.find(kBoardPlaceholder, offset)) != std::string::npos) {
    value.replace(offset, std::char_traits<char>::length(kBoardPlaceholder), board_id);
    offset += board_id.size();
  }
  return value;
}

std::string BoardPrefix(const std::string& board_id) {
  return std::string(kNodePrefix) + board_id + ".";
}

std::vector<std::string> ExtractPlaceholders(const std::string& pattern) {
  std::vector<std::string> result;
  const std::regex placeholder(R"(\{([^{}]+)\})");
  for (auto match = std::sregex_iterator(pattern.begin(), pattern.end(), placeholder);
       match != std::sregex_iterator(); ++match) {
    result.push_back((*match)[1].str());
  }
  return result;
}

std::regex NodePatternRegex(const std::string& pattern) {
  constexpr std::string_view kRegexSpecial = R"(\.^$|()[]*+?)";
  std::string expression = "^";
  for (size_t index = 0; index < pattern.size();) {
    if (pattern[index] == '{') {
      const size_t close = pattern.find('}', index + 1);
      if (close == std::string::npos) {
        throw std::runtime_error("unterminated telemetry placeholder in " + pattern);
      }
      const std::string placeholder = pattern.substr(index + 1, close - index - 1);
      expression += placeholder == "Service" || placeholder == "Device" ? "(.+)" : "([^.]+)";
      index = close + 1;
      continue;
    }
    if (kRegexSpecial.find(pattern[index]) != std::string_view::npos) expression.push_back('\\');
    expression.push_back(pattern[index]);
    ++index;
  }
  expression += '$';
  return std::regex(expression);
}

const google::protobuf::Descriptor* SampleDescriptor(CatalogValueType type) {
  switch (type) {
    case CatalogValueType::Boolean:
      return daphne::telemetry::v8::BooleanSample::descriptor();
    case CatalogValueType::Integer:
      return daphne::telemetry::v8::IntegerSample::descriptor();
    case CatalogValueType::Long:
      return daphne::telemetry::v8::LongSample::descriptor();
    case CatalogValueType::Double:
      return daphne::telemetry::v8::DoubleSample::descriptor();
    case CatalogValueType::String:
      return daphne::telemetry::v8::StringSample::descriptor();
    case CatalogValueType::DateTime:
      return daphne::telemetry::v8::DateTimeSample::descriptor();
  }
  throw std::runtime_error("unknown catalog value type");
}

std::optional<int64_t> ParseProcValueKib(const std::string& key) {
  std::ifstream input("/proc/meminfo");
  std::string name;
  int64_t value = 0;
  std::string unit;
  while (input >> name >> value >> unit) {
    if (name == key + ":") return value * 1024;
  }
  return std::nullopt;
}

std::map<std::string, std::string> ReadOsRelease() {
  std::map<std::string, std::string> values;
  std::ifstream input("/etc/os-release");
  std::string line;
  while (std::getline(input, line)) {
    const auto separator = line.find('=');
    if (separator == std::string::npos) continue;
    std::string value = Trim(line.substr(separator + 1));
    if (value.size() >= 2 && value.front() == '"' && value.back() == '"') {
      value = value.substr(1, value.size() - 2);
    }
    values[Trim(line.substr(0, separator))] = value;
  }
  return values;
}

std::map<std::string, std::string> ReadBoardConfiguration() {
  std::map<std::string, std::string> values;
  for (const std::filesystem::path path : {"/etc/default/firmware", "/etc/daphne-board.env"}) {
    std::ifstream input(path);
    std::string line;
    while (std::getline(input, line)) {
      line = Trim(line);
      if (line.empty() || line.front() == '#') continue;
      const auto separator = line.find('=');
      if (separator == std::string::npos) continue;
      std::string value = Trim(line.substr(separator + 1));
      if (value.size() >= 2 && ((value.front() == '"' && value.back() == '"') ||
                                (value.front() == '\'' && value.back() == '\''))) {
        value = value.substr(1, value.size() - 2);
      }
      values[Trim(line.substr(0, separator))] = value;
    }
  }
  return values;
}

std::map<std::string, std::string> ReadServiceProperties(const std::string& service) {
  struct CacheEntry {
    std::chrono::steady_clock::time_point collected_at{};
    std::map<std::string, std::string> properties;
  };
  static std::mutex cache_mutex;
  static std::map<std::string, CacheEntry> cache;
  std::lock_guard<std::mutex> cache_lock(cache_mutex);
  const auto now = std::chrono::steady_clock::now();
  const auto cached = cache.find(service);
  if (cached != cache.end() && now - cached->second.collected_at < std::chrono::seconds(5)) {
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
    const std::string line = Trim(buffer.data());
    const auto separator = line.find('=');
    if (separator != std::string::npos)
      properties[Trim(line.substr(0, separator))] = Trim(line.substr(separator + 1));
  }
  (void)pclose(pipe);
  cache[service] = CacheEntry{now, properties};
  return properties;
}

std::optional<std::pair<std::string, int32_t>> ReadIpv4Address(const std::string& interface) {
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

std::optional<std::string> ReadDefaultGateway(const std::string& interface) {
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

std::string ReadDnsServers() {
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

std::optional<int64_t> ReadBootTimeNs() {
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

const CatalogEntry* CatalogBegin() { return std::begin(kCatalog); }
const CatalogEntry* CatalogEnd() { return std::end(kCatalog); }
size_t CatalogSize() { return std::size(kCatalog); }

uint64_t UnixTimeNs() {
  return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                   std::chrono::system_clock::now().time_since_epoch())
                                   .count());
}

uint64_t MonotonicTimeNs() {
  return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
                                   std::chrono::steady_clock::now().time_since_epoch())
                                   .count());
}

std::string DetectBoardId() {
  if (const auto configured = GetEnvironment("DAPHNE_TELEMETRY_BOARD_ID")) return *configured;
  if (const auto configured = GetEnvironment("DAPHNE_BOARD_ID")) return *configured;
  std::array<char, 256> hostname{};
  if (gethostname(hostname.data(), hostname.size() - 1) == 0) {
    std::string value(hostname.data());
    std::smatch match;
    if (std::regex_search(value, match,
                          std::regex("(?:^|-)DAPHNE-([0-9]+)(?:\\.|$)", std::regex::icase))) {
      return match[1].str();
    }
    const auto dash = value.find_last_of('-');
    if (dash != std::string::npos && dash + 1 < value.size()) {
      const std::string suffix = value.substr(dash + 1);
      if (std::all_of(suffix.begin(), suffix.end(),
                      [](unsigned char ch) { return std::isdigit(ch); }))
        return suffix;
    }
    if (!value.empty()) return value;
  }
  return "unknown";
}

SnapshotBuilder::SnapshotBuilder(const ReadTelemetrySnapshotRequest& request, std::string board_id)
    : board_id_(std::move(board_id)),
      snapshot_time_ns_(UnixTimeNs()),
      snapshot_monotonic_ns_(MonotonicTimeNs()) {
  response_.set_success(true);
  response_.set_message("DAPHNE proposed-v8 explicit telemetry snapshot");
  response_.set_schema_major(2);
  response_.set_schema_minor(0);
  response_.set_schema_source_sha256(DAPHNE_TELEMETRY_SCHEMA_SHA256);
  response_.set_contract_revision("PDS-DAQ-ICD-proposed-v8-explicit-2026-08-18");
  response_.set_board_id(board_id_);
  response_.set_request_sequence(request.request_sequence());
  response_.set_snapshot_sequence(++g_snapshot_sequence);
  response_.set_snapshot_time_unix_ns(snapshot_time_ns_);
  response_.set_snapshot_monotonic_ns(snapshot_monotonic_ns_);

  timex clock_state{};
  const int clock_result = adjtimex(&clock_state);
  response_.set_wall_clock_synchronized(clock_result >= 0 &&
                                        (clock_state.status & STA_UNSYNC) == 0);

  for (const CatalogEntry& entry : kCatalog) {
    const std::string node_id = ReplaceBoardId(entry.node_id, board_id_);
    catalog_by_node_id_.emplace(node_id, &entry);
  }
  InitializeWireContract();
}

const std::string& SnapshotBuilder::board_id() const { return board_id_; }

std::string SnapshotBuilder::NodeId(const std::string& suffix) const {
  return BoardPrefix(board_id_) + suffix;
}

void SnapshotBuilder::InitializeWireContract() {
  using google::protobuf::FieldDescriptor;
  using google::protobuf::Message;

  auto* telemetry = response_.mutable_telemetry();
  const auto* descriptor = telemetry->GetDescriptor();
  const auto* reflection = telemetry->GetReflection();
  for (int field_index = 0; field_index < descriptor->field_count(); ++field_index) {
    const FieldDescriptor* field = descriptor->field(field_index);
    const auto& options = field->options();
    if (!options.HasExtension(daphne::telemetry::v8::opcua_node_pattern)) {
      throw std::runtime_error("BoardTelemetry field has no OPC-UA contract annotation: " +
                               field->full_name());
    }

    const std::string pattern =
        ReplaceBoardId(options.GetExtension(daphne::telemetry::v8::opcua_node_pattern), board_id_);
    const std::string unit = options.GetExtension(daphne::telemetry::v8::engineering_unit);
    const std::string source = options.GetExtension(daphne::telemetry::v8::data_source);
    const std::vector<std::string> placeholders = ExtractPlaceholders(pattern);

    if (!field->is_repeated()) {
      if (!placeholders.empty()) {
        throw std::runtime_error("non-repeated wire field contains an instance placeholder: " +
                                 field->full_name());
      }
      const auto catalog = catalog_by_node_id_.find(pattern);
      if (catalog == catalog_by_node_id_.end()) {
        throw std::runtime_error("wire field is absent from board catalog: " + pattern);
      }
      if (unit != catalog->second->engineering_unit || source != catalog->second->source) {
        throw std::runtime_error("wire annotation differs from board catalog: " + pattern);
      }
      RegisterSample(pattern, *catalog->second, reflection->MutableMessage(telemetry, field));
      continue;
    }

    if (placeholders.empty()) {
      throw std::runtime_error("repeated wire field has no instance placeholder: " +
                               field->full_name());
    }
    const std::regex matcher = NodePatternRegex(pattern);
    size_t matched_entries = 0;
    for (const auto& [node_id, catalog] : catalog_by_node_id_) {
      std::smatch match;
      if (!std::regex_match(node_id, match, matcher)) continue;
      if (match.size() != placeholders.size() + 1) {
        throw std::runtime_error("wire instance match has wrong capture count: " + node_id);
      }
      if (unit != catalog->engineering_unit || source != catalog->source) {
        throw std::runtime_error("wire annotation differs from board catalog: " + node_id);
      }

      Message* entry = reflection->AddMessage(telemetry, field);
      const auto* entry_descriptor = entry->GetDescriptor();
      const auto* entry_reflection = entry->GetReflection();
      const FieldDescriptor* sample_field = entry_descriptor->FindFieldByName("sample");
      if (sample_field == nullptr || sample_field->cpp_type() != FieldDescriptor::CPPTYPE_MESSAGE ||
          entry_descriptor->field_count() != static_cast<int>(placeholders.size()) + 1) {
        throw std::runtime_error("wire instance wrapper has an invalid declared shape: " +
                                 entry_descriptor->full_name());
      }
      for (size_t placeholder = 0; placeholder < placeholders.size(); ++placeholder) {
        const FieldDescriptor* key_field = entry_descriptor->field(static_cast<int>(placeholder));
        if (key_field == sample_field || key_field->cpp_type() != FieldDescriptor::CPPTYPE_STRING) {
          throw std::runtime_error("wire instance wrapper key is not a declared string for {" +
                                   placeholders[placeholder] +
                                   "}: " + entry_descriptor->full_name());
        }
        entry_reflection->SetString(entry, key_field, match[placeholder + 1].str());
      }
      RegisterSample(node_id, *catalog, entry_reflection->MutableMessage(entry, sample_field));
      ++matched_entries;
    }
    if (matched_entries == 0) {
      throw std::runtime_error("wire field matches no board instances: " + field->full_name());
    }
  }

  if (samples_by_node_id_.size() != catalog_by_node_id_.size()) {
    throw std::runtime_error("explicit wire contract covers " +
                             std::to_string(samples_by_node_id_.size()) + " of " +
                             std::to_string(catalog_by_node_id_.size()) + " board variables");
  }
}

void SnapshotBuilder::RegisterSample(const std::string& node_id, const CatalogEntry& entry,
                                     google::protobuf::Message* sample) {
  using google::protobuf::FieldDescriptor;
  if (sample == nullptr || sample->GetDescriptor() != SampleDescriptor(entry.value_type)) {
    throw std::runtime_error("wire sample type mismatch for " + node_id);
  }
  const FieldDescriptor* value_field = sample->GetDescriptor()->FindFieldByName("value");
  const FieldDescriptor* metadata_field = sample->GetDescriptor()->FindFieldByName("metadata");
  if (value_field == nullptr || metadata_field == nullptr ||
      metadata_field->cpp_type() != FieldDescriptor::CPPTYPE_MESSAGE) {
    throw std::runtime_error("wire sample lacks value or metadata for " + node_id);
  }
  const auto [unused, inserted] =
      samples_by_node_id_.emplace(node_id, SampleBinding{sample, value_field, entry.value_type});
  if (!inserted) throw std::runtime_error("duplicate explicit wire binding for " + node_id);
  InitializeSampleMetadata(sample);
}

daphne::telemetry::v8::SampleMetadata* SnapshotBuilder::MutableMetadata(
    google::protobuf::Message* sample) {
  const auto* metadata_field = sample->GetDescriptor()->FindFieldByName("metadata");
  auto* metadata_message = sample->GetReflection()->MutableMessage(sample, metadata_field);
  auto* metadata = dynamic_cast<daphne::telemetry::v8::SampleMetadata*>(metadata_message);
  if (metadata == nullptr) throw std::runtime_error("wire sample has wrong metadata type");
  return metadata;
}

void SnapshotBuilder::InitializeSampleMetadata(google::protobuf::Message* sample) const {
  auto* metadata = MutableMetadata(sample);
  metadata->set_quality(TELEMETRY_QUALITY_UNAVAILABLE);
  metadata->set_sample_time_unix_ns(snapshot_time_ns_);
  metadata->set_sample_monotonic_ns(snapshot_monotonic_ns_);
  metadata->set_error_code(0);
  metadata->set_detail("No value supplied by this collector/firmware");
}

SnapshotBuilder::SampleBinding* SnapshotBuilder::FindSample(const std::string& node_id,
                                                            CatalogValueType expected_type,
                                                            TelemetryQuality quality,
                                                            const std::string& detail) {
  const auto catalog_entry = catalog_by_node_id_.find(node_id);
  if (catalog_entry == catalog_by_node_id_.end()) {
    AddDiagnostic(DIAGNOSTIC_SEVERITY_WARNING, "collector", 2,
                  "Collector attempted unknown NodeId: " + node_id);
    return nullptr;
  }
  if (catalog_entry->second->value_type != expected_type) {
    AddDiagnostic(DIAGNOSTIC_SEVERITY_WARNING, "collector", 3,
                  "Collector type mismatch for NodeId: " + node_id);
    return nullptr;
  }

  const auto binding = samples_by_node_id_.find(node_id);
  if (binding == samples_by_node_id_.end() || binding->second.value_type != expected_type) {
    AddDiagnostic(DIAGNOSTIC_SEVERITY_WARNING, "wire-contract", 4,
                  "No typed Protobuf field is bound to NodeId: " + node_id);
    return nullptr;
  }
  auto* metadata = MutableMetadata(binding->second.sample);
  metadata->set_quality(quality);
  metadata->set_detail(detail);
  metadata->set_error_code(0);
  if (!QualityHasValue(quality)) {
    binding->second.sample->GetReflection()->ClearField(binding->second.sample,
                                                        binding->second.value_field);
  }
  return &binding->second;
}

bool SnapshotBuilder::SetBoolean(const std::string& id, bool value, TelemetryQuality quality,
                                 const std::string& detail) {
  auto* binding = FindSample(id, CatalogValueType::Boolean, quality, detail);
  if (binding == nullptr) return false;
  if (QualityHasValue(quality)) {
    binding->sample->GetReflection()->SetBool(binding->sample, binding->value_field, value);
  }
  return true;
}

bool SnapshotBuilder::SetInteger(const std::string& id, int32_t value, TelemetryQuality quality,
                                 const std::string& detail) {
  auto* binding = FindSample(id, CatalogValueType::Integer, quality, detail);
  if (binding == nullptr) return false;
  if (QualityHasValue(quality)) {
    binding->sample->GetReflection()->SetInt32(binding->sample, binding->value_field, value);
  }
  return true;
}

bool SnapshotBuilder::SetLong(const std::string& id, int64_t value, TelemetryQuality quality,
                              const std::string& detail) {
  auto* binding = FindSample(id, CatalogValueType::Long, quality, detail);
  if (binding == nullptr) return false;
  if (QualityHasValue(quality)) {
    binding->sample->GetReflection()->SetInt64(binding->sample, binding->value_field, value);
  }
  return true;
}

bool SnapshotBuilder::SetDouble(const std::string& id, double value, TelemetryQuality quality,
                                const std::string& detail) {
  auto* binding = FindSample(id, CatalogValueType::Double, quality, detail);
  if (binding == nullptr) return false;
  if (!std::isfinite(value)) {
    auto* metadata = MutableMetadata(binding->sample);
    metadata->set_quality(TELEMETRY_QUALITY_INVALID);
    metadata->set_detail("Collector returned a non-finite number");
    binding->sample->GetReflection()->ClearField(binding->sample, binding->value_field);
    return false;
  }
  if (QualityHasValue(quality)) {
    binding->sample->GetReflection()->SetDouble(binding->sample, binding->value_field, value);
  }
  return true;
}

bool SnapshotBuilder::SetString(const std::string& id, const std::string& value,
                                TelemetryQuality quality, const std::string& detail) {
  auto* binding = FindSample(id, CatalogValueType::String, quality, detail);
  if (binding == nullptr) return false;
  if (QualityHasValue(quality)) {
    binding->sample->GetReflection()->SetString(binding->sample, binding->value_field, value);
  }
  return true;
}

bool SnapshotBuilder::SetDateTime(const std::string& id, int64_t value, TelemetryQuality quality,
                                  const std::string& detail) {
  auto* binding = FindSample(id, CatalogValueType::DateTime, quality, detail);
  if (binding == nullptr) return false;
  if (QualityHasValue(quality)) {
    binding->sample->GetReflection()->SetInt64(binding->sample, binding->value_field, value);
  }
  return true;
}

bool SnapshotBuilder::SetSampleTimes(const std::string& id, uint64_t unix_ns,
                                     uint64_t monotonic_ns) {
  const auto binding = samples_by_node_id_.find(id);
  if (binding == samples_by_node_id_.end()) return false;
  auto* metadata = MutableMetadata(binding->second.sample);
  metadata->set_sample_time_unix_ns(unix_ns);
  metadata->set_sample_monotonic_ns(monotonic_ns);
  return true;
}

void SnapshotBuilder::AddDiagnostic(daphne::telemetry::v8::DiagnosticSeverity severity,
                                    const std::string& component, uint32_t code,
                                    const std::string& message) {
  auto* diagnostic = response_.add_diagnostics();
  diagnostic->set_severity(severity);
  diagnostic->set_component(component);
  diagnostic->set_code(code);
  diagnostic->set_message(message);
  diagnostic->set_first_seen_time_unix_ns(snapshot_time_ns_);
  diagnostic->set_last_seen_time_unix_ns(snapshot_time_ns_);
  diagnostic->set_occurrence_count(1);
}

void SnapshotBuilder::CollectPlatformTelemetry() {
  CollectIdentity();
  CollectNetwork();
  CollectHost();
  CollectFirmwareAndDevices();
  CollectServices();
  CollectRpu();
}

void SnapshotBuilder::CollectIdentity() {
  const std::string base = BoardPrefix(board_id());
  SetString(base + "Identity.BoardId", board_id());

  std::array<char, 256> hostname{};
  if (gethostname(hostname.data(), hostname.size() - 1) == 0) {
    SetString(base + "Identity.Hostname", hostname.data());
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
    if (const auto value = GetEnvironment(name)) SetString(base + suffix, *value);
  }
  if (const auto expected = GetEnvironment("DAPHNE_EXPECTED_HOSTNAME")) {
    SetBoolean(base + "Identity.HostnameMatch", *expected == hostname.data());
  }
}

void SnapshotBuilder::CollectNetwork() {
  const std::string base = BoardPrefix(board_id());
  const std::string interface = GetEnvironment("DAPHNE_MANAGEMENT_INTERFACE").value_or("eth0");
  const std::string network = base + "Network.Interfaces." + interface + ".";
  const std::filesystem::path sys_interface = "/sys/class/net/" + interface;
  if (std::filesystem::exists(sys_interface)) {
    SetString(network + "Name", interface);
    if (const auto value = ReadText(sys_interface / "address"))
      SetString(network + "MacAddress", *value);
    if (const auto value = ReadText(sys_interface / "operstate"))
      SetString(network + "OperationalState", *value);
    if (const auto value = ReadInteger(sys_interface / "carrier"))
      SetBoolean(network + "Carrier", *value != 0);
    if (const auto value = ReadInteger(sys_interface / "speed"))
      SetInteger(network + "SpeedMbps", static_cast<int32_t>(*value));
    if (const auto value = ReadText(sys_interface / "duplex"))
      SetString(network + "Duplex", *value);
    if (const auto value = ReadInteger(sys_interface / "mtu"))
      SetInteger(network + "MtuBytes", static_cast<int32_t>(*value));
    const std::array<std::pair<const char*, const char*>, 8> statistics{{
        {"rx_bytes", "RxBytes"},
        {"rx_packets", "RxPackets"},
        {"rx_errors", "RxErrors"},
        {"rx_dropped", "RxDropped"},
        {"tx_bytes", "TxBytes"},
        {"tx_packets", "TxPackets"},
        {"tx_errors", "TxErrors"},
        {"tx_dropped", "TxDropped"},
    }};
    for (const auto& [file, suffix] : statistics) {
      if (const auto value = ReadInteger(sys_interface / "statistics" / file))
        SetLong(network + suffix, *value);
    }
  }
  if (const auto address = ReadIpv4Address(interface)) {
    SetString(network + "Ipv4Address", address->first);
    SetInteger(network + "PrefixLength", address->second);
  }
  if (const auto gateway = ReadDefaultGateway(interface))
    SetString(network + "DefaultGateway", *gateway);
  const std::string dns = ReadDnsServers();
  if (!dns.empty()) SetString(network + "DnsServers", dns);
}

void SnapshotBuilder::CollectHost() {
  const std::string base = BoardPrefix(board_id());
  const uint64_t now = UnixTimeNs();
  SetDateTime(base + "Host.CurrentUtc", static_cast<int64_t>(now));
  SetLong(base + "Host.UnixTimeNs", static_cast<int64_t>(now));
  if (const auto uptime = ReadText("/proc/uptime")) {
    try {
      SetLong(base + "Host.UptimeSeconds", static_cast<int64_t>(std::stod(*uptime)));
    } catch (...) {
    }
  }
  if (const auto value = ReadText("/proc/sys/kernel/random/boot_id"))
    SetString(base + "Host.BootId", *value);
  if (const auto value = ReadBootTimeNs()) SetDateTime(base + "Host.BootTime", *value);
  utsname uts{};
  if (uname(&uts) == 0) SetString(base + "Host.KernelRelease", uts.release);
  const auto release = ReadOsRelease();
  const auto pretty = release.find("PRETTY_NAME");
  if (pretty != release.end()) SetString(base + "Host.OperatingSystemVersion", pretty->second);
  if (const auto value = GetEnvironment("DAPHNE_ROOTFS_BUILD_ID"))
    SetString(base + "Host.RootFilesystemBuildId", *value);
  if (const auto value = GetEnvironment("DAPHNE_ACTIVE_BOOT_SLOT"))
    SetString(base + "Host.ActiveBootSlot", *value);
  if (const auto value = GetEnvironment("DAPHNE_LAST_RESET_REASON"))
    SetString(base + "Host.LastResetReason", *value);
  timex clock_state{};
  const int clock_result = adjtimex(&clock_state);
  if (clock_result >= 0) {
    const bool synchronized = (clock_state.status & STA_UNSYNC) == 0;
    SetBoolean(base + "Host.NtpSynchronized", synchronized);
    SetDouble(base + "Host.NtpOffsetMilliseconds",
              static_cast<double>(clock_state.offset) / 1000.0);
    SetString(base + "Host.TimeSource", synchronized ? "kernel-ntp-disciplined" : "unsynchronized");
  }
  std::array<double, 3> loads{};
  if (getloadavg(loads.data(), static_cast<int>(loads.size())) > 0)
    SetDouble(base + "Host.CpuLoad1Minute", loads[0]);
  if (const auto value = ParseProcValueKib("MemAvailable"))
    SetLong(base + "Host.MemoryAvailableBytes", *value);
  struct statvfs filesystem_status{};
  if (statvfs("/", &filesystem_status) == 0) {
    SetLong(base + "Host.RootFilesystemFreeBytes",
            static_cast<int64_t>(filesystem_status.f_bavail) *
                static_cast<int64_t>(filesystem_status.f_frsize));
#ifdef ST_RDONLY
    SetBoolean(base + "Host.RootFilesystemReadOnly", (filesystem_status.f_flag & ST_RDONLY) != 0);
#endif
  }
}

void SnapshotBuilder::CollectFirmwareAndDevices() {
  const std::string base = BoardPrefix(board_id());
  const auto board_config = ReadBoardConfiguration();
  const std::filesystem::path fpga_state = "/sys/class/fpga_manager/fpga0/state";
  if (const auto state = ReadText(fpga_state)) {
    SetString(base + "Firmware.FpgaManagerState", *state);
    SetBoolean(base + "Firmware.Loaded", *state == "operating");
  }
  SetBoolean(base + "Firmware.PlI2cDevicePresent",
             std::filesystem::exists("/sys/bus/platform/devices/9c000000.i2c") ||
                 std::filesystem::exists("/dev/i2c-1") || std::filesystem::exists("/dev/i2c-2"));
  SetBoolean(base + "Firmware.PlSpiDevicePresent",
             std::filesystem::exists("/sys/bus/platform/devices/9c020000.axi_quad_spi") ||
                 std::filesystem::exists("/dev/spidev3.0"));
  SetBoolean(base + "Firmware.FirmwarePathAvailable", std::filesystem::exists("/lib/firmware"));
  SetString(base + "Firmware.ServerVersion", DAPHNE_SERVER_VERSION);
  SetString(base + "Firmware.ProtobufSchemaVersion", "daphne.telemetry.v8/2.0");
  if (const auto value = GetEnvironment("DAPHNE_FIRMWARE_BUILD_ID"))
    SetString(base + "Firmware.BuildId", *value);
  auto firmware_app = board_config.find("FIRMWARE_APP");
  if (firmware_app == board_config.end()) firmware_app = board_config.find("APP");
  if (firmware_app != board_config.end() && !firmware_app->second.empty()) {
    SetString(base + "Firmware.OverlayName", firmware_app->second);
    SetString(base + "Firmware.ActiveXmutilApplication", firmware_app->second);
    const auto separator = firmware_app->second.find_last_of('_');
    if (!GetEnvironment("DAPHNE_FIRMWARE_BUILD_ID") && separator != std::string::npos &&
        separator + 1 < firmware_app->second.size()) {
      SetString(base + "Firmware.BuildId", firmware_app->second.substr(separator + 1));
    }
  }
  if (const auto value = GetEnvironment("DAPHNE_FIRMWARE_EXPECTED_BUILD_ID")) {
    SetString(base + "Firmware.ExpectedBuildId", *value);
    if (const auto current = GetEnvironment("DAPHNE_FIRMWARE_BUILD_ID"))
      SetBoolean(base + "Firmware.BuildMatchesExpected", *value == *current);
  }
  if (const auto value = GetEnvironment("DAPHNE_ACTIVE_XMUTIL_APPLICATION"))
    SetString(base + "Firmware.ActiveXmutilApplication", *value);

  for (const std::string bus : {"1", "2"}) {
    const std::string bus_base = base + "I2C.Buses." + bus + ".";
    const std::string path = "/dev/i2c-" + bus;
    const bool present = std::filesystem::exists(path);
    SetBoolean(bus_base + "Present", present);
    SetString(bus_base + "Path", path);
    // A device node proves enumeration, not successful I2C transactions. The
    // hardware collector supplies Functional only when it has a real probe.
    SetString(bus_base + "Owner", "daphne.service");
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
    const std::filesystem::path sys_path =
        std::filesystem::path("/sys/bus/i2c/devices") / sys_name.str();
    const bool present = std::filesystem::exists(sys_path);
    SetBoolean(device_base + "Present", present,
               present ? TELEMETRY_QUALITY_GOOD : TELEMETRY_QUALITY_UNAVAILABLE,
               present ? "registered in Linux sysfs" : "not enumerated; no active probe performed");
    if (const auto value = ReadText(sys_path / "name"))
      SetString(device_base + "Name", *value);
    else
      SetString(device_base + "Name", device.name);
    if (present) {
      SetString(device_base + "Status", "present");
      std::error_code error;
      const auto driver = std::filesystem::read_symlink(sys_path / "driver", error);
      if (!error) SetString(device_base + "Driver", driver.filename().string());
    } else {
      SetString(device_base + "Status", "not-enumerated", TELEMETRY_QUALITY_UNAVAILABLE);
    }
  }
  const std::string spi_base = base + "SPI.spidev3.0.";
  const bool spi_present = std::filesystem::exists("/dev/spidev3.0");
  SetBoolean(spi_base + "Present", spi_present);
  // Presence alone does not prove that a transfer succeeds. Leave Functional
  // unavailable until an active, non-invasive probe is implemented.
  SetString(spi_base + "Owner", "daphne.service");
}

void SnapshotBuilder::CollectServices() {
  const std::string base = BoardPrefix(board_id());
  const std::array<const char*, 6> services{{
      "firmware.service",
      "clockchip.service",
      "endpoint.service",
      "hermes.service",
      "daphne.service",
      "daphne-boot-ok.service",
  }};
  for (const char* service : services) {
    const auto properties = ReadServiceProperties(service);
    if (properties.empty()) continue;
    const std::string service_base = base + "Services." + service + ".";
    const auto active = properties.find("ActiveState");
    if (active != properties.end()) {
      SetString(service_base + "State", active->second);
      SetBoolean(service_base + "Active", active->second == "active");
      if (std::string(service) == "daphne-boot-ok.service")
        SetBoolean(base + "Host.BootMarkedGood", active->second == "active");
    }
    const auto pid = properties.find("MainPID");
    if (pid != properties.end()) {
      try {
        SetInteger(service_base + "MainPid", std::stoi(pid->second));
      } catch (...) {
      }
    }
    const auto restarts = properties.find("NRestarts");
    if (restarts != properties.end()) {
      try {
        SetInteger(service_base + "RestartCount", std::stoi(restarts->second));
      } catch (...) {
      }
    }
    const auto exit_status = properties.find("ExecMainStatus");
    if (exit_status != properties.end())
      SetString(service_base + "LastExitStatus", exit_status->second);
  }
}

void SnapshotBuilder::CollectRpu() {
  const std::string base = BoardPrefix(board_id());
  std::filesystem::path remoteproc_root = "/sys/class/remoteproc";
  std::error_code directory_error;
  bool rpu_available = false;
  if (std::filesystem::exists(remoteproc_root, directory_error)) {
    for (const auto& item : std::filesystem::directory_iterator(remoteproc_root, directory_error)) {
      const auto name = ReadText(item.path() / "name");
      if (!name ||
          (name->find("r5") == std::string::npos && name->find("R5") == std::string::npos &&
           name->find("rpu") == std::string::npos && name->find("RPU") == std::string::npos))
        continue;
      rpu_available = true;
      if (const auto value = ReadText(item.path() / "state")) {
        SetBoolean(base + "RPU.Running", *value == "running");
        SetBoolean(base + "Services.rpu.Active", *value == "running");
        SetString(base + "Services.rpu.State", *value);
      }
      if (const auto value = ReadText(item.path() / "firmware"))
        SetString(base + "RPU.Firmware", *value);
      break;
    }
  }
  SetBoolean(base + "RPU.Available", rpu_available,
             rpu_available ? TELEMETRY_QUALITY_GOOD : TELEMETRY_QUALITY_UNAVAILABLE);
}

ReadTelemetrySnapshotResponse SnapshotBuilder::Finish() { return std::move(response_); }

}  // namespace daphne_sc::telemetry
