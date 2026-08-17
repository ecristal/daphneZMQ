#pragma once

#include <unordered_map>

#include "server_controller/handlers.hpp"

namespace daphne_sc {

class SlowControlBackend;

std::unordered_map<daphne::MessageTypeV2, V2Handler> make_emulated_v2_handlers(
    SlowControlBackend& backend);

}  // namespace daphne_sc
