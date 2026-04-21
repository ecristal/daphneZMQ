#pragma once

#include <functional>
#include <string>
#include <unordered_map>

#include "daphneV3_high_level_confs.pb.h"

class Daphne;

namespace daphne_sc {

using V2Handler = std::function<void(const std::string& req_payload, std::string& resp_payload, Daphne& daphne)>;

std::unordered_map<daphne::MessageTypeV2, V2Handler> make_v2_handlers();

}  // namespace daphne_sc

