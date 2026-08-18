#ifndef DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_HPP_
#define DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_HPP_

#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>

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

const CatalogEntry* CatalogBegin();
const CatalogEntry* CatalogEnd();
size_t CatalogSize();

std::string DetectBoardId();
uint64_t UnixTimeNs();
uint64_t MonotonicTimeNs();

class SnapshotBuilder {
 public:
  SnapshotBuilder(const daphne::telemetry::v8::ReadTelemetrySnapshotRequest& request,
                  std::string board_id);
  ~SnapshotBuilder() = default;

  SnapshotBuilder(const SnapshotBuilder&) = delete;
  SnapshotBuilder& operator=(const SnapshotBuilder&) = delete;
  SnapshotBuilder(SnapshotBuilder&&) noexcept = default;
  SnapshotBuilder& operator=(SnapshotBuilder&&) noexcept = default;

  const std::string& board_id() const;
  std::string NodeId(const std::string& suffix) const;

  bool SetBoolean(const std::string& node_id, bool value,
                  daphne::telemetry::v8::TelemetryQuality quality =
                      daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                  const std::string& detail = "");
  bool SetInteger(const std::string& node_id, int32_t value,
                  daphne::telemetry::v8::TelemetryQuality quality =
                      daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                  const std::string& detail = "");
  bool SetLong(const std::string& node_id, int64_t value,
               daphne::telemetry::v8::TelemetryQuality quality =
                   daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
               const std::string& detail = "");
  bool SetDouble(const std::string& node_id, double value,
                 daphne::telemetry::v8::TelemetryQuality quality =
                     daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                 const std::string& detail = "");
  bool SetString(const std::string& node_id, const std::string& value,
                 daphne::telemetry::v8::TelemetryQuality quality =
                     daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                 const std::string& detail = "");
  bool SetDateTime(const std::string& node_id, int64_t unix_ns,
                   daphne::telemetry::v8::TelemetryQuality quality =
                       daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD,
                   const std::string& detail = "");
  bool SetSampleTimes(const std::string& node_id, uint64_t unix_ns, uint64_t monotonic_ns);

  void AddDiagnostic(daphne::telemetry::v8::DiagnosticSeverity severity,
                     const std::string& component, uint32_t code, const std::string& message);

  void CollectPlatformTelemetry();
  daphne::telemetry::v8::ReadTelemetrySnapshotResponse Finish();

 private:
  void CollectIdentity();
  void CollectNetwork();
  void CollectHost();
  void CollectFirmwareAndDevices();
  void CollectServices();
  void CollectRpu();

  struct SampleBinding {
    google::protobuf::Message* sample = nullptr;
    const google::protobuf::FieldDescriptor* value_field = nullptr;
    CatalogValueType value_type = CatalogValueType::Boolean;
  };

  void InitializeWireContract();
  void RegisterSample(const std::string& node_id, const CatalogEntry& entry,
                      google::protobuf::Message* sample);
  SampleBinding* FindSample(const std::string& node_id, CatalogValueType expected_type,
                            daphne::telemetry::v8::TelemetryQuality quality,
                            const std::string& detail);
  void InitializeSampleMetadata(google::protobuf::Message* sample) const;
  static daphne::telemetry::v8::SampleMetadata* MutableMetadata(google::protobuf::Message* sample);

  std::string board_id_;
  uint64_t snapshot_time_ns_ = 0;
  uint64_t snapshot_monotonic_ns_ = 0;
  daphne::telemetry::v8::ReadTelemetrySnapshotResponse response_;
  std::unordered_map<std::string, const CatalogEntry*> catalog_by_node_id_;
  std::unordered_map<std::string, SampleBinding> samples_by_node_id_;
};

}  // namespace daphne_sc::telemetry

#endif  // DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_HPP_
