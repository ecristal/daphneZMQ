#ifndef DAPHNE_SERVER_CONTROLLER_V8_HARDWARE_TELEMETRY_HPP_
#define DAPHNE_SERVER_CONTROLLER_V8_HARDWARE_TELEMETRY_HPP_

#include "daphne_v8_telemetry.pb.h"
#include "server_controller/handlers.hpp"

class Daphne;

namespace daphne_sc::telemetry {

daphne::telemetry::v8::ReadTelemetrySnapshotResponse CollectHardwareSnapshot(
    const daphne::telemetry::v8::ReadTelemetrySnapshotRequest& request, Daphne& daphne);
V2Handler MakeHardwareSnapshotHandler(Daphne& board);

}  // namespace daphne_sc::telemetry

#endif  // DAPHNE_SERVER_CONTROLLER_V8_HARDWARE_TELEMETRY_HPP_
