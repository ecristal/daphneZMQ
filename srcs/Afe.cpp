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

uint32_t Afe::setAFEFunction(const uint32_t& afe, const std::string& functionName, const uint16_t& value){
    
	auto available_options_it = this->afeFunctionAvailableOptionsDict.find(functionName);
	if (available_options_it == this->afeFunctionAvailableOptionsDict.end()) {
		std::cerr << "Function name:" << functionName << " not found in the available options dictionary." << std::endl;
		return 0;
	}

	const auto& available_options = available_options_it->second;
	int len_options = available_options.size();
	if(len_options == 2){
		if(value >= available_options[0] && value <= available_options[1]){
			std::cout << "Value is in range." << std::endl;
		}else{
			std::cerr << "Value is out of range." << std::endl;
			return 0;
		}
	}else{
		if(std::find(available_options.begin(), available_options.end(), static_cast<uint16_t>(value)) == available_options.end()){
			std::cerr << "Value is not in the available options." << std::endl;
			return 0;
		}
	}

	auto afe_funct_it = this->afeFunctionDict.find(functionName);
	if (afe_funct_it == this->afeFunctionDict.end()) {
		std::cerr << "Function name not found in the dictionary." << std::endl;
		return 0;
	}

	const Afe::BitField& bit_field = afe_funct_it->second;
	const auto& registerAddr = bit_field.begin()->first;
	const auto& msb_pos = bit_field.begin()->second.first;
	const auto& lsb_pos = bit_field.begin()->second.second;
	uint32_t mask = ((1 << (msb_pos - lsb_pos + 1)) - 1) << lsb_pos;
	uint32_t registerValue = this->getRegister(afe, registerAddr);
	registerValue = (registerValue & (~mask)); // Clear the bits
	registerValue |= ((value << lsb_pos) & mask); // Set the new value
	this->setRegister(afe, registerAddr, registerValue);
	registerValue = this->getRegister(afe, registerAddr);
	// get the written bits to check if they are correct
	uint32_t checkValue = (registerValue & mask) >> lsb_pos;
	if(checkValue != value){
		std::cerr << "Written value different than read value (AFE: " << afe
		     << ", REG: " << registerAddr
		     << ", W: " << value
		     << ", R: " << checkValue
		     << ")" << std::endl;
	}
	return checkValue;
}