#pragma once

#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc {

// Protocol-facing boundary for slow-control implementations.  The production
// server continues to use the existing hardware handlers while operations are
// migrated behind this interface.  The emulator implements the interface
// without requiring /dev/mem, I2C, or an FPGA.
class SlowControlBackend {
 public:
  virtual ~SlowControlBackend() = default;

  virtual void boot() {}

  virtual daphne::ConfigureResponse configure(const daphne::ConfigureRequest& request) = 0;
  virtual daphne::ReadTriggerCountersResponse read_trigger_counters(
      const daphne::ReadTriggerCountersRequest& request) const = 0;
  virtual daphne::TestRegResponse read_test_register() const = 0;
  virtual daphne::GeneralInfo read_general_info(const daphne::InfoRequest& request) const = 0;
};

}  // namespace daphne_sc
