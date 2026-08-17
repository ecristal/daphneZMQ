#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>

#include "daphne_v8_telemetry.pb.h"

namespace daphne_sc::telemetry {

enum class CatalogValueType {
  Boolean,
  Integer,
  Long,
  Double,
  String,
  DateTime,
};

struct CatalogEntry {
  const char* node_id;
  CatalogValueType value_type;
  const char* engineering_unit;
  const char* source;
};

const CatalogEntry* catalog_begin();
const CatalogEntry* catalog_end();
size_t catalog_size();

std::string detect_board_id();
uint64_t unix_time_ns();
uint64_t monotonic_time_ns();

class SnapshotBuilder {
 public:
  SnapshotBuilder(const daphne::telemetry::v8::ReadTelemetrySnapshotRequest& request,
                  std::string board_id);
  ~SnapshotBuilder();

  SnapshotBuilder(const SnapshotBuilder&) = delete;
  SnapshotBuilder& operator=(const SnapshotBuilder&) = delete;
  SnapshotBuilder(SnapshotBuilder&&) noexcept;
  SnapshotBuilder& operator=(SnapshotBuilder&&) noexcept;

  const std::string& board_id() const;
  std::string node(const std::string& suffix) const;

  bool set_boolean(const std::string& node_id, bool value,
                   daphne::telemetry::v8::TelemetryQuality quality =
                       daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                   const std::string& detail = "");
  bool set_integer(const std::string& node_id, int32_t value,
                   daphne::telemetry::v8::TelemetryQuality quality =
                       daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                   const std::string& detail = "");
  bool set_long(const std::string& node_id, int64_t value,
                daphne::telemetry::v8::TelemetryQuality quality =
                    daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                const std::string& detail = "");
  bool set_double(const std::string& node_id, double value,
                  daphne::telemetry::v8::TelemetryQuality quality =
                      daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                  const std::string& detail = "");
  bool set_string(const std::string& node_id, const std::string& value,
                  daphne::telemetry::v8::TelemetryQuality quality =
                      daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                  const std::string& detail = "");
  bool set_datetime(const std::string& node_id, int64_t unix_ns,
                    daphne::telemetry::v8::TelemetryQuality quality =
                        daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                    const std::string& detail = "");
  bool set_sample_times(const std::string& node_id, uint64_t unix_ns,
                        uint64_t monotonic_ns);

  void add_diagnostic(daphne::telemetry::v8::DiagnosticSeverity severity,
                      const std::string& component, uint32_t code,
                      const std::string& message);

  void collect_platform();
  daphne::telemetry::v8::ReadTelemetrySnapshotResponse finish();

 private:
  class Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace daphne_sc::telemetry
