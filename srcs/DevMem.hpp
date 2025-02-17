#ifndef DEVMEM_HPP
#define DEVMEM_HPP

#include <cstdint>
#include <string>
#include <vector>
#include <stdexcept>
#include <sstream>
#include <iostream>
#include <iomanip>

class DevMem {
public:
    // Constructor
    DevMem(uint64_t base_addr, const std::string& filename = "/dev/mem");

    // Destructor
    ~DevMem();

    // Read words
    std::vector<uint32_t> read(size_t offset, size_t num_words);

    // Write words
    void write(size_t offset, const std::vector<uint32_t>& data);

    // Hexdump for debugging
    std::string hexdump(const std::vector<uint32_t>& data);
    void changeBaseAddr(const uint64_t &base_addr, const size_t length);
    void map_memory(size_t length);
private:
    size_t page_size;     // System page size
    size_t word_size;     // Word size in bytes

    int fd_;                    // File descriptor
    void* mem_;                 // Memory-mapped region
    uint64_t base_addr_;        // Page-aligned base address
    size_t offset_;             // Offset within the page
    size_t length_;             // Total length of mapped memory
    std::string filename_;      // File name (default: /dev/mem)

    // Align length to page size
    size_t align_to_page(size_t length) const;

    // Validate offset and length
    void validate_offset(size_t offset, size_t num_words) const;
};

#endif // DEVMEM_HPP
