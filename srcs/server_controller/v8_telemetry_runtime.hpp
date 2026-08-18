#ifndef DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_RUNTIME_HPP_
#define DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_RUNTIME_HPP_

#include <cstdint>
#include <string>

#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc::telemetry {

class SnapshotBuilder;

void BeginCommand(const daphne::ControlEnvelopeV2& envelope, const std::string& requester);
void CompleteCommand(uint64_t message_id, bool handler_succeeded, const std::string& result);
void RecordActiveConfiguration(const daphne::ConfigureRequest& configuration);
void CollectRuntimeTelemetry(SnapshotBuilder& builder);

}  // namespace daphne_sc::telemetry

#endif  // DAPHNE_SERVER_CONTROLLER_V8_TELEMETRY_RUNTIME_HPP_
