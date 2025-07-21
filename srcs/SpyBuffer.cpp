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

uint32_t SpyBuffer::getMappedData(uint32_t sample) const {
    const uint32_t* ptr = channel_ptrs[this->current_channel_index];
    uint32_t raw_word = ptr[sample / 2];
    if (sample % 2 == 0) {
        return (raw_word >> 2) & 0x3FFF; // DATAL
    } else {
        return (raw_word >> 18) & 0x3FFF; // DATAH
    }
}

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