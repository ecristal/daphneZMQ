#pragma once

#include "daphne_v8_telemetry.pb.h"

class Daphne;

namespace daphne_sc::telemetry {

daphne::telemetry::v8::ReadTelemetrySnapshotResponse collect_hardware_snapshot(
    const daphne::telemetry::v8::ReadTelemetrySnapshotRequest& request,
    Daphne& daphne);

}  // namespace daphne_sc::telemetry
