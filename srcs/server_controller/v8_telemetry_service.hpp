#ifndef DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_SERVICE_HPP_
#define DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_SERVICE_HPP_

#include <functional>

#include "daphne_v8_telemetry.pb.h"
#include "server_controller/handlers.hpp"

namespace daphne_sc::telemetry {

// The single protobuf-facing entry point for v8 telemetry. A collector only
// has to build the typed snapshot; this adapter owns request parsing and
// response serialization for both the hardware server and the emulator.
using SnapshotCollector = std::function<daphne::telemetry::v8::ReadTelemetrySnapshotResponse(
    const daphne::telemetry::v8::ReadTelemetrySnapshotRequest&)>;

V2Handler MakeSnapshotHandler(SnapshotCollector collect);

}  // namespace daphne_sc::telemetry

#endif  // DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_SERVICE_HPP_
