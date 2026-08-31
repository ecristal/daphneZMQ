#include "server_controller/devmem_mmio.hpp"

#include <limits>
#include <stdexcept>

namespace daphne_sc {

DevMemWindowMmio32::DevMemWindowMmio32(uint64_t base_address, size_t length)
    : base_address_(base_address), length_(length), memory_(base_address) {
  if (length_ == 0 || length_ % sizeof(uint32_t) != 0) {
    throw std::invalid_argument("MMIO window length must be a non-zero multiple of four");
  }
  memory_.map_memory(length_);
}

size_t DevMemWindowMmio32::offset_for(uint64_t address) const {
  if (address < base_address_ || address - base_address_ > std::numeric_limits<size_t>::max()) {
    throw std::out_of_range("MMIO address is outside the mapped window");
  }
  const size_t offset = static_cast<size_t>(address - base_address_);
  if (offset % sizeof(uint32_t) != 0 || offset > length_ - sizeof(uint32_t)) {
    throw std::out_of_range("MMIO address is outside the mapped window");
  }
  return offset;
}

uint32_t DevMemWindowMmio32::read32(uint64_t address) {
  return memory_.read_u32(offset_for(address));
}

void DevMemWindowMmio32::write32(uint64_t address, uint32_t value) {
  memory_.write_u32(offset_for(address), value);
}

}  // namespace daphne_sc
