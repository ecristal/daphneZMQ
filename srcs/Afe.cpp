#include "Afe.hpp"

Afe::Afe()
	: spi(std::make_unique<Spi>()){}

Afe::~Afe(){}

uint32_t Afe::setReset(const uint32_t& reset){

	uint32_t value = this->spi->getFpgaReg()->setBits("afeGlobalControl", "RESET", reset);
	return value;
}

uint32_t Afe::doReset(){

	uint32_t value = this->setReset(1);
	std::this_thread::sleep_for(std::chrono::microseconds(100));
	value = this->setReset(0);
	return value;
}

uint32_t Afe::setPowerdown(const uint32_t& powerdown){

	uint32_t value = this->spi->getFpgaReg()->setBits("afeGlobalControl", "POWERDOWN", ~powerdown);
	std::this_thread::sleep_for(std::chrono::microseconds(5000));
	return value;
}

uint32_t Afe::getPowerdown(){

	return this->spi->getFpgaReg()->getBits("afeGlobalControl", "POWERDOWN");
}

uint32_t Afe::setRegister(const uint32_t& afe, const uint32_t& register_, const uint32_t& value){

	uint32_t value_ = (register_ & 0xff) << 16 | (value & 0xFFFF);
	std::string regString = "afeControl_" + std::to_string(afe);
	this->spi->setData(regString, value_);
	this->spi->setData(regString, 0x000002);
	this->spi->setData(regString, value_ & 0xFF0000);
	uint32_t readValue = this->spi->getData(regString) & 0xFFFF;
	this->spi->setData(regString, 0x000000);
	if(readValue != (value_ & 0xFFFF)){
		std::cout << "Read value different than written value (AFE: " << afe
		     << ", REG: 0x" << std::hex << register_
		     << ", W: 0x" << (value_ & 0xFFFF)
		     << ", R: 0x" << readValue
		     << ")" << std::endl;
	}
	return readValue;
}

uint32_t Afe::getRegister(const uint32_t& afe, const uint32_t& register_){

	std::string regString = "afeControl_" + std::to_string(afe);
	this->spi->setData(regString, 0x000002);
	this->spi->setData(regString, register_ << 16);
	uint32_t value_ = this->spi->getData(regString) & 0xFFFF;
	this->spi->setData(regString, 0x000000);
	return value_;
}

uint32_t Afe::initAFE(const uint32_t& afe, const std::unordered_map<uint32_t, uint32_t> &regDict){

	uint32_t value_;
	for(const auto& reg_ : regDict){
		value_ = this->setRegister(afe, reg_.first, reg_.second);
	}

	return value_;
}