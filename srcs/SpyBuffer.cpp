#include "SpyBuffer.hpp"

SpyBuffer::SpyBuffer()
	: fpgaReg(std::make_unique<FpgaReg>()){}

SpyBuffer::~SpyBuffer(){}

uint32_t SpyBuffer::getFrameClock(const uint32_t& afe, const uint32_t& sample){

	return this->fpgaReg->getBits("spyBuffer_" + std::to_string(afe) + "_8", "DATA", sample*4);
}

uint32_t SpyBuffer::getData(const uint32_t& afe, const uint32_t& ch, const uint32_t& sample){
    
    std::string bitStr = "";
	if(sample % 2 ){
		bitStr = "DATAH";
	}else{
		bitStr = "DATAL";
	}
	//std::cout << "Sample: " << (uint32_t)((double)sample/2) << std::endl;
	return this->fpgaReg->getBits("spyBuffer_" + std::to_string(afe) + "_" + std::to_string(ch), bitStr, (uint32_t)(((double)sample)/2.0));
}

double SpyBuffer::getOutputVoltage(const uint32_t& afe, const uint32_t& ch, const uint32_t& sample){

	double vRef = 1.0;
	uint32_t value = this->getData(afe,ch,sample);
	double value_d = (double) value;
	value_d = ((value_d - 8192.0)/8192.0)*vRef;
	//std:: cout << "data: " << value_d << std::endl;
	return value_d;
}