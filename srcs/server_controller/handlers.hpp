#pragma once

#include <functional>
#include <string>
#include <unordered_map>

#include "daphneV3_high_level_confs.pb.h"

class Daphne;

namespace daphne_sc {

using V2Handler = std::function<void(const std::string& req_payload, std::string& resp_payload)>;
using V2ResponseSink = std::function<void(const std::string& resp_payload)>;
using V2StreamingHandler =
    std::function<void(const std::string& req_payload, const V2ResponseSink& send_response)>;

std::unordered_map<daphne::MessageTypeV2, V2Handler> make_v2_handlers(Daphne& daphne);
std::unordered_map<daphne::MessageTypeV2, V2Handler> make_v8_telemetry_handlers(
    Daphne& daphne);

}  // namespace daphne_sc
