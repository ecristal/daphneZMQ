#include "SpyBuffer.hpp"

SpyBuffer::SpyBuffer()
	: fpgaReg(std::make_unique<FpgaReg>()){}

SpyBuffer::~SpyBuffer(){}

uint32_t SpyBuffer::getFrameClock(const uint32_t& afe, const uint32_t& sample){

	return this->fpgaReg->getBits("spyBuffer_" + std::to_string(afe) + "_8", "DATA", sample*4);
}

uint32_t SpyBuffer::getData(const uint32_t& sample){
    
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