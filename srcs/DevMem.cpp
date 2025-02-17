#include "DevMem.hpp"
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>

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
    this->base_addr_ = base_addr & ~(page_size - 1);
    this->offset_ = base_addr - base_addr_;
    this->length_ = align_to_page(length + offset_);
    
    // Open the file
    this->fd_ = open(filename_.c_str(), O_RDWR | O_SYNC);
    if (this->fd_ == -1) {
        throw std::runtime_error("Failed to open " + filename_);
    }

    // Map the memory
    this->mem_ = mmap(nullptr, length_, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, base_addr_);
    if (this->mem_ == MAP_FAILED) {
        close(this->fd_);
        throw std::runtime_error("Failed to mmap memory");
    }
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
    // Map the memory
    this->length_ = align_to_page(length + this->offset_);
    mem_ = mmap(nullptr, this->length_, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, base_addr_);
    if (mem_ == MAP_FAILED) {
        close(fd_);
        throw std::runtime_error("Failed to mmap memory");
    }
}
