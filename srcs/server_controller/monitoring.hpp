#pragma once

#include <chrono>
#include <thread>
#include <vector>

class Daphne;

namespace daphne_sc {

struct MonitoringOptions {
  std::chrono::milliseconds period{200};
};

std::vector<std::thread> start_monitoring(Daphne& daphne, const MonitoringOptions& options);

}  // namespace daphne_sc

