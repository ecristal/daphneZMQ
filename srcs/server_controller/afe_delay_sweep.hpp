#pragma once

#include <string>

#include "daphneV3_high_level_confs.pb.h"

class Daphne;

namespace daphne_sc {

bool run_afe_delay_sweep(const daphne::AfeDelaySweepRequest& request,
                         daphne::AfeDelaySweepResponse& response,
                         Daphne& daphne,
                         std::string& response_str);

}  // namespace daphne_sc
