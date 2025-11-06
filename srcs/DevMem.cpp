#include "DevMem.hpp"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

// Constructor
DevMem::DevMem(uint64_t base_addr, const std::string& filename)
    : page_size(sysconf(_SC_PAGESIZE)),
      word_size(sizeof(uint32_t)),
      base_addr_(base_addr & ~(page_size - 1)),
      offset_(base_addr - base_addr_),
      length_(0),
      filename_(filename),
      fd_(-1),
      mem_(MAP_FAILED) {

    // Open the file
    fd_ = open(filename_.c_str(), O_RDWR | O_SYNC);
    if (fd_ == -1) {
        throw std::runtime_error("Failed to open " + filename_);
    }
}

// Destructor
DevMem::~DevMem() {
    if (mem_ != MAP_FAILED) {
        munmap(mem_, length_);
    }
    if (fd_ != -1) {
        close(fd_);
    }
}

void DevMem::changeBaseAddr(const uint64_t &base_addr, const size_t length){
    if (length == 0) {
        throw std::invalid_argument("Length must be greater than zero");
    }

    if (mem_ != MAP_FAILED) {
        munmap(mem_, length_);
        mem_ = MAP_FAILED;
        length_ = 0;
    }

    base_addr_ = base_addr & ~(static_cast<uint64_t>(page_size) - 1);
    offset_ = base_addr - base_addr_;

    const size_t new_length = align_to_page(length + offset_);
    void* new_mapping = mmap(nullptr,
                             new_length,
                             PROT_READ | PROT_WRITE,
                             MAP_SHARED,
                             fd_,
                             base_addr_);
    if (new_mapping == MAP_FAILED) {
        const int err = errno;
        throw std::runtime_error(
            std::string("Failed to mmap memory: ") + std::strerror(err));
    }

    mem_ = new_mapping;
    length_ = new_length;
}

// Align length to page size
size_t DevMem::align_to_page(size_t length) const {
    return (length + page_size - 1) & ~(page_size - 1);
}

// Validate offset and length
void DevMem::validate_offset(size_t offset, size_t num_words) const {
    if ((offset % word_size) != 0) {
        throw std::invalid_argument("Offset must be aligned to word size");
    }
    if ((offset + num_words * word_size) > length_) {
        throw std::out_of_range("Read/write operation exceeds memory bounds");
    }
}

// Read words
std::vector<uint32_t> DevMem::read(size_t offset, size_t num_words) {
    validate_offset(offset, num_words);
    auto* mem_ptr = static_cast<uint32_t*>(mem_);
    std::vector<uint32_t> data(num_words);

    for (size_t i = 0; i < num_words; ++i) {
        data[i] = mem_ptr[(offset_ + offset) / word_size + i];
    }

    return data;
}

const uint32_t* DevMem::get_read_ptr(size_t offset, size_t num_words){
    validate_offset(offset, num_words);
    auto* mem_ptr = static_cast<uint32_t*>(mem_);
    return mem_ptr + (offset_ + offset) / word_size;
}

// Write words
void DevMem::write(size_t offset, const std::vector<uint32_t>& data) {
    validate_offset(offset, data.size());
    auto* mem_ptr = static_cast<uint32_t*>(mem_);

    for (size_t i = 0; i < data.size(); ++i) {
        mem_ptr[(offset_ + offset) / word_size + i] = data[i];
    }
}

// Hexdump for debugging
std::string DevMem::hexdump(const std::vector<uint32_t>& data) {
    std::ostringstream oss;
    for (size_t i = 0; i < data.size(); ++i) {
        if (i % 4 == 0) oss << std::endl;
        oss << "0x" << std::hex << std::setw(8) << std::setfill('0') << data[i] << " ";
    }
    return oss.str();
}

void DevMem::map_memory(size_t length){
    if (length == 0) {
        throw std::invalid_argument("Length must be greater than zero");
    }

    if (mem_ != MAP_FAILED) {
        munmap(mem_, length_);
        mem_ = MAP_FAILED;
        length_ = 0;
    }

    const size_t new_length = align_to_page(length + offset_);
    void* new_mapping = mmap(nullptr,
                             new_length,
                             PROT_READ | PROT_WRITE,
                             MAP_SHARED,
                             fd_,
                             base_addr_);
    if (new_mapping == MAP_FAILED) {
        const int err = errno;
        throw std::runtime_error(
            std::string("Failed to mmap memory: ") + std::strerror(err));
    }

    mem_ = new_mapping;
    length_ = new_length;
}
