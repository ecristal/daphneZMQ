#include "SpyBuffer.hpp"

#include <cstdlib>

namespace {

uint64_t readDurationEnvironment(const char* name, uint64_t default_value) {
    const char* raw = std::getenv(name);
    if (raw == nullptr || *raw == '\0') {
        return default_value;
    }

    try {
        size_t consumed = 0;
        const unsigned long long value = std::stoull(raw, &consumed, 10);
        if (consumed != std::string(raw).size()) {
            throw std::invalid_argument("trailing characters");
        }
        return static_cast<uint64_t>(value);
    } catch (const std::exception&) {
        throw std::invalid_argument(
            std::string("Invalid unsigned integer in environment variable ") +
            name + ": " + raw);
    }
}

}  // namespace

SpyBuffer::SpyBuffer()
    : fpgaReg(std::make_unique<FpgaReg>()),
      channel_ptrs{},
      timestamp_ptrs{},
      current_channel_index(0),
      trigger_wait_timeout(
          readDurationEnvironment("DAPHNE_SPYBUFFER_TRIGGER_TIMEOUT_MS", 30000)),
      timestamp_poll_interval(
          readDurationEnvironment("DAPHNE_SPYBUFFER_TIMESTAMP_POLL_US", 100)) {
        this->mapToArraySpyBufferRegisters();
        this->mapTimestampRegisters();
    }

SpyBuffer::~SpyBuffer(){}

uint32_t SpyBuffer::getFrameClock(const uint32_t& afe, const uint32_t& sample){

	const uint32_t* ptr = this->fpgaReg->getRegisterPointer("spyBuffer_" + std::to_string(afe) + "_8", "DATA", sample);
	if (!ptr) {
		return 0;
	}
	return *ptr;  // full 32-bit word; caller can mask as needed
}

uint32_t SpyBuffer::getData(const uint32_t& sample) const{
    
	bool bitEndianess;
	if(sample % 2 ){
		//bitStr = "DATAH";
		bitEndianess = true;
	}else{
		//bitStr = "DATAL";
		bitEndianess = false;
	}
	return this->fpgaReg->getBitsFast((uint32_t)(((double)sample)/2.0), bitEndianess);
}

// uint32_t SpyBuffer::getMappedData(uint32_t sample) const {
//     const uint32_t* ptr = channel_ptrs[this->current_channel_index];
//     uint32_t raw_word = ptr[sample / 2];
//     if (sample % 2 == 0) {
//         return (raw_word >> 2) & 0x3FFF; // DATAL
//     } else {
//         return (raw_word >> 18) & 0x3FFF; // DATAH
//     }
// }

double SpyBuffer::getOutputVoltage(const uint32_t& sample){

	double vRef = 1.0;
	uint32_t value = this->getData(sample);
	double value_d = (double) value;
	value_d = ((value_d - 8192.0)/8192.0)*vRef;
	//std:: cout << "data: " << value_d << std::endl;
	return value_d;
}

void SpyBuffer::cacheSpyBufferRegister(const uint32_t& afe, const uint32_t& ch){
	
	this->fpgaReg->getRegisterAndCacheData("spyBuffer_" + std::to_string(afe) + "_" + std::to_string(ch));
}

void SpyBuffer::mapToArraySpyBufferRegisters(){
	int afeNum = 5;
	int channelNum = 8;
	for(int afe = 0; afe < afeNum; afe++){
		for(int ch = 0; ch < channelNum; ch++){
			int channel_index = 8*afe + ch;
			this->channel_ptrs[channel_index] = this->fpgaReg->getRegisterPointer("spyBuffer_" + std::to_string(afe) + "_" + std::to_string(ch),"DATAL",0);
		}
	}
}

void SpyBuffer::mapTimestampRegisters(){
    for (size_t i = 0; i < timestamp_ptrs.size(); ++i) {
        const uint32_t* ptr = this->fpgaReg->getRegisterPointer(
            "timestamp" + std::to_string(i), "VALUE", 0);
        if (ptr == nullptr) {
            throw std::runtime_error(
                "Could not map timestamp" + std::to_string(i));
        }
        timestamp_ptrs[i] = ptr;
    }
}

void SpyBuffer::setCurrentMappedChannelIndex(uint32_t index){
	this->current_channel_index = index;
}

const uint32_t* SpyBuffer::getCurrentChannelDataPointer() const {
    return channel_ptrs[this->current_channel_index];
}

const uint32_t* SpyBuffer::getChannelDataPointer(uint32_t index) const {
    return channel_ptrs[index];
}

void SpyBuffer::extractMappedDataBulk(uint32_t* output, uint32_t numberOfSamples) const {
    const uint32_t* ptr = channel_ptrs[this->current_channel_index];
    uint32_t wordCount = numberOfSamples / 2;
    uint32_t idx = 0;
    for (uint32_t w = 0; w < wordCount; ++w) {
        uint32_t raw_word = ptr[w];
        output[idx++] = (raw_word >> 2) & 0x3FFF;   // DATAL
        output[idx++] = (raw_word >> 18) & 0x3FFF;  // DATAH
    }
    if (numberOfSamples % 2) {
        uint32_t raw_word = ptr[wordCount];
        output[idx++] = (raw_word >> 2) & 0x3FFF;   // Last DATAL
    }
}

void SpyBuffer::extractMappedDataBulkSIMD(uint32_t* dst, uint32_t nSamples) {
    
	uint32_t wordCount = nSamples / 2;
    uint32_t idx = 0;
    uint32_t i = 0;

    const uint32_t* src = channel_ptrs[this->current_channel_index];
    // Process 4 words at a time (8 samples)
    
    for (; i + 3 < wordCount; i += 4) {
        uint32x4_t words = vld1q_u32(src + i);

        // For DATAL (bits 2–15)
        uint32x4_t datal = vandq_u32(vshrq_n_u32(words, 2), vdupq_n_u32(0x3FFF));
        // For DATAH (bits 18–31)
        uint32x4_t datah = vandq_u32(vshrq_n_u32(words, 18), vdupq_n_u32(0x3FFF));

        // Interleave and store results
        // Write DATAL
        vst1q_lane_u32(dst + idx,     datal, 0);
        vst1q_lane_u32(dst + idx + 2, datal, 1);
        vst1q_lane_u32(dst + idx + 4, datal, 2);
        vst1q_lane_u32(dst + idx + 6, datal, 3);
        // Write DATAH
        vst1q_lane_u32(dst + idx + 1, datah, 0);
        vst1q_lane_u32(dst + idx + 3, datah, 1);
        vst1q_lane_u32(dst + idx + 5, datah, 2);
        vst1q_lane_u32(dst + idx + 7, datah, 3);

        idx += 8;
    }
    
    for (; i < wordCount; ++i) {
        uint32_t word = src[i];
        dst[idx++] = (word >> 2) & 0x3FFF;    // DATAL
        dst[idx++] = (word >> 18) & 0x3FFF;   // DATAH
    }
    if (nSamples % 2) {
        uint32_t word = src[wordCount];
        dst[idx++] = (word >> 2) & 0x3FFF;    // DATAL
    }
}

// void SpyBuffer::extractMappedDataBulkSIMD(uint32_t* dst, uint32_t nSamples, uint32_t channel_index) {
    
// 	uint32_t wordCount = nSamples / 2;
//     uint32_t idx = 0;
//     uint32_t i = 0;

//     const uint32_t* src = channel_ptrs[channel_index];
//     // Process 4 words at a time (8 samples)
//     for (; i + 3 < wordCount; i += 4) {
//         uint32x4_t words = vld1q_u32(src + i);

//         // For DATAL (bits 2–15)
//         uint32x4_t datal = vandq_u32(vshrq_n_u32(words, 2), vdupq_n_u32(0x3FFF));
//         // For DATAH (bits 18–31)
//         uint32x4_t datah = vandq_u32(vshrq_n_u32(words, 18), vdupq_n_u32(0x3FFF));

//         // Interleave and store results
//         // Write DATAL
//         vst1q_lane_u32(dst + idx,     datal, 0);
//         vst1q_lane_u32(dst + idx + 2, datal, 1);
//         vst1q_lane_u32(dst + idx + 4, datal, 2);
//         vst1q_lane_u32(dst + idx + 6, datal, 3);
//         // Write DATAH
//         vst1q_lane_u32(dst + idx + 1, datah, 0);
//         vst1q_lane_u32(dst + idx + 3, datah, 1);
//         vst1q_lane_u32(dst + idx + 5, datah, 2);
//         vst1q_lane_u32(dst + idx + 7, datah, 3);

//         idx += 8;
//     }

//     for (; i < wordCount; ++i) {
//         uint32_t word = src[i];
//         dst[idx++] = (word >> 2) & 0x3FFF;    // DATAL
//         dst[idx++] = (word >> 18) & 0x3FFF;   // DATAH
//     }
//     if (nSamples % 2) {
//         uint32_t word = src[wordCount];
//         dst[idx++] = (word >> 2) & 0x3FFF;    // DATAL
//     }
// }

void SpyBuffer::extractMappedDataBulkSIMD(uint32_t* dst, uint32_t nSamples, uint32_t channel_index) {
    uint32_t wordCount = nSamples / 2;
    const uint32_t* src = channel_ptrs[channel_index];

    // SIMD: process in chunks of 4 words (8 samples)
    uint32_t simd_limit = (wordCount / 4) * 4;

    // Parallelize the SIMD section
    #pragma omp parallel for
    for (uint32_t i = 0; i < simd_limit; i += 4) {
        uint32x4_t words = vld1q_u32(src + i);

        // DATAL: bits 2-15
        uint32x4_t datal = vandq_u32(vshrq_n_u32(words, 2), vdupq_n_u32(0x3FFF));
        // DATAH: bits 18-31
        uint32x4_t datah = vandq_u32(vshrq_n_u32(words, 18), vdupq_n_u32(0x3FFF));

        // Write interleaved to dst (be careful: idx depends on i!)
        uint32_t idx = i * 2;
        vst1q_lane_u32(dst + idx,     datal, 0);
        vst1q_lane_u32(dst + idx + 2, datal, 1);
        vst1q_lane_u32(dst + idx + 4, datal, 2);
        vst1q_lane_u32(dst + idx + 6, datal, 3);

        vst1q_lane_u32(dst + idx + 1, datah, 0);
        vst1q_lane_u32(dst + idx + 3, datah, 1);
        vst1q_lane_u32(dst + idx + 5, datah, 2);
        vst1q_lane_u32(dst + idx + 7, datah, 3);
    }

    // Handle any leftovers (if wordCount not multiple of 4)
    uint32_t idx = simd_limit * 2;
    for (uint32_t i = simd_limit; i < wordCount; ++i) {
        uint32_t word = src[i];
        dst[idx++] = (word >> 2) & 0x3FFF;    // DATAL
        dst[idx++] = (word >> 18) & 0x3FFF;   // DATAH
    }

    // Odd sample out (if nSamples is odd)
    if (nSamples % 2) {
        uint32_t word = src[wordCount];
        dst[idx++] = (word >> 2) & 0x3FFF;    // DATAL
    }
}

SpyBuffer::TimestampKey SpyBuffer::getTimestampKey(const uint32_t& sample) const {
    TimestampKey timestamp{};
    for (size_t i = 0; i < timestamp_ptrs.size(); ++i) {
        timestamp[i] = static_cast<uint16_t>(timestamp_ptrs[i][sample] & 0xFFFFu);
    }
    return timestamp;
}

uint64_t SpyBuffer::packTimestamp(const TimestampKey& timestamp) {
    return static_cast<uint64_t>(timestamp[0]) |
           (static_cast<uint64_t>(timestamp[1]) << 16) |
           (static_cast<uint64_t>(timestamp[2]) << 32) |
           (static_cast<uint64_t>(timestamp[3]) << 48);
}

bool SpyBuffer::waitExpired(
    const std::chrono::steady_clock::time_point& deadline) const {
    return deadline != std::chrono::steady_clock::time_point::max() &&
           std::chrono::steady_clock::now() >= deadline;
}

SpyBuffer::TimestampKey SpyBuffer::acquireFreshMappedData(
    uint32_t* dst,
    uint32_t nSamples,
    const std::vector<uint32_t>& channel_indices,
    const std::function<void()>& issue_trigger) {
    if (dst == nullptr) {
        throw std::invalid_argument("Spybuffer destination pointer is null");
    }
    if (nSamples == 0 || nSamples > 2048) {
        throw std::invalid_argument("Spybuffer sample count is out of range");
    }
    if (channel_indices.empty()) {
        throw std::invalid_argument("Spybuffer channel list is empty");
    }
    for (const uint32_t channel : channel_indices) {
        if (channel >= channel_ptrs.size()) {
            throw std::invalid_argument("Mapped spybuffer channel is out of range");
        }
    }

    std::unique_lock<std::mutex> lock(acquisition_mutex);
    const auto deadline = trigger_wait_timeout.count() == 0
        ? std::chrono::steady_clock::time_point::max()
        : std::chrono::steady_clock::now() + trigger_wait_timeout;

    TimestampKey current = this->getTimestampKey();
    std::optional<TimestampKey> baseline;

    if (issue_trigger) {
        // A software-triggered acquisition waits until the command advances the
        // timestamp beyond the snapshot that existed before the command.
        baseline = current;
        issue_trigger();
    } else if (last_delivered_timestamp.has_value()) {
        baseline = last_delivered_timestamp;
    }

    while (baseline.has_value() && current == *baseline) {
        if (this->waitExpired(deadline)) {
            throw std::runtime_error(
                "Timed out waiting for a new spybuffer trigger");
        }
        std::this_thread::sleep_for(timestamp_poll_interval);
        current = this->getTimestampKey();
    }

    for (size_t i = 0; i < channel_indices.size(); ++i) {
        this->extractMappedDataBulkSIMD(
            dst + static_cast<size_t>(nSamples) * i,
            nSamples,
            channel_indices[i]);
    }

    last_delivered_timestamp = current;
    return current;
}
