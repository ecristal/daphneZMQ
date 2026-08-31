#pragma once

#include <cstddef>
#include <cstdint>

#include "DevMem.hpp"
#include "server_controller/gateware.hpp"

namespace daphne_sc {

class DevMemWindowMmio32 final : public Mmio32 {
 public:
  DevMemWindowMmio32(uint64_t base_address, size_t length);

  uint32_t read32(uint64_t address) override;
  void write32(uint64_t address, uint32_t value) override;

 private:
  size_t offset_for(uint64_t address) const;

  uint64_t base_address_;
  size_t length_;
  DevMem memory_;
};

}  // namespace daphne_sc
