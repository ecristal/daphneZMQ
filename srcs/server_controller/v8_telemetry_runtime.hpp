#pragma once

#include <cstdint>
#include <string>

#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc::telemetry {

class SnapshotBuilder;

bool is_audited_command(daphne::MessageTypeV2 type);
void begin_command(const daphne::ControlEnvelopeV2& envelope,
                   const std::string& requester);
void complete_command(uint64_t message_id, bool handler_succeeded,
                      const std::string& result);
void record_active_configuration(const daphne::ConfigureRequest& configuration);
void collect_runtime(SnapshotBuilder& builder);

}  // namespace daphne_sc::telemetry
