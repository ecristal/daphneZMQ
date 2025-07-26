#include "SpyBuffer.hpp"

SpyBuffer::SpyBuffer()
	: fpgaReg(std::make_unique<FpgaReg>()){
		this->mapToArraySpyBufferRegisters();
	}

SpyBuffer::~SpyBuffer(){}

uint32_t SpyBuffer::getFrameClock(const uint32_t& afe, const uint32_t& sample){

	return this->fpgaReg->getBits("spyBuffer_" + std::to_string(afe) + "_8", "DATA", sample);
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

void SpyBuffer::extractMappedDataBulkSIMD(uint32_t* dst, uint32_t nSamples, uint32_t channel_index) {
    
	uint32_t wordCount = nSamples / 2;
    uint32_t idx = 0;
    uint32_t i = 0;

    const uint32_t* src = channel_ptrs[channel_index];
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
