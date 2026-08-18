#include "server_controller/v8_telemetry_service.hpp"

#include <stdexcept>
#include <utility>

namespace daphne_sc::telemetry {

V2Handler MakeSnapshotHandler(SnapshotCollector collect) {
  return [collect = std::move(collect)](const std::string& input, std::string& output) {
    daphne::telemetry::v8::ReadTelemetrySnapshotRequest request;
    daphne::telemetry::v8::ReadTelemetrySnapshotResponse response;

    if (!request.ParseFromString(input)) {
      response.set_success(false);
      response.set_message("Bad ReadTelemetrySnapshotRequest payload");
    } else {
      response = collect(request);
    }

    if (!response.SerializeToString(&output)) {
      throw std::runtime_error("Could not serialize ReadTelemetrySnapshotResponse");
    }
  };
}

}  // namespace daphne_sc::telemetry
