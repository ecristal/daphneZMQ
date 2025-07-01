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

uint32_t Afe::setPowerState(const uint32_t& powerstate){

	uint32_t value = this->spi->getFpgaReg()->setBits("afeGlobalControl", "POWERSTATE", powerstate);
	std::this_thread::sleep_for(std::chrono::microseconds(5000));
	return value;
}

uint32_t Afe::getPowerState(){

	return this->spi->getFpgaReg()->getBits("afeGlobalControl", "POWERSTATE");
}

uint32_t Afe::setRegister(const uint32_t& afe, const uint32_t& register_, const uint32_t& value){

	if(std::find(this->register_list.begin(), this->register_list.end(), register_) == this->register_list.end()){
		throw std::invalid_argument("Register address " + std::to_string(register_) + " not found in AFE register list.");
		return 0;
	}

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

	if(std::find(this->register_list.begin(), this->register_list.end(), register_) == this->register_list.end()){
		throw std::invalid_argument("Register address " + std::to_string(register_) + " not found in AFE register list.");
		return 0;
	}

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
		throw std::invalid_argument("AFE function name " + functionName + " not found in the AFE options dictionary.");
		return 0;
	}

	const auto& available_options = available_options_it->second;
	int len_options = available_options.size();
	if(len_options == 2){
		if(value >= available_options[0] && value <= available_options[1]){
			std::cout << "Value is in range." << std::endl;
		}else{
			throw std::invalid_argument("Invalid value " + std::to_string(value) + " for AFE function name " + functionName + 
			                            ".\nThe expected range is " + std::to_string(available_options[0]) + " - " + std::to_string(available_options[1]));
			return 0;
		}
	}else{
		if(std::find(available_options.begin(), available_options.end(), static_cast<uint16_t>(value)) == available_options.end()){
			std::string options_list = "\n";
			for(const auto &option_ : available_options){
				options_list = options_list + std::to_string(option_) + "\n";
			}
			throw std::invalid_argument("Invalid option " + std::to_string(value) + " for AFE function name " + functionName + 
			                            ".\nThe expected option list is: " + options_list);
			return 0;
		}
	}

	auto afe_funct_it = this->afeFunctionDict.find(functionName);
	if (afe_funct_it == this->afeFunctionDict.end()) {
		throw std::invalid_argument("AFE function name " + functionName + " not found in the AFE functions dictionary.");
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

uint32_t Afe::getAFEFunction(const uint32_t& afe, const std::string& functionName){

	auto afe_funct_it = this->afeFunctionDict.find(functionName);
	if (afe_funct_it == this->afeFunctionDict.end()) {
		throw std::invalid_argument("AFE function name " + functionName + " not found in the AFE functions dictionary.");
		return 0;
	}

	const Afe::BitField& bit_field = afe_funct_it->second;
	const auto& registerAddr = bit_field.begin()->first;
	const auto& msb_pos = bit_field.begin()->second.first;
	const auto& lsb_pos = bit_field.begin()->second.second;
	uint32_t mask = ((1 << (msb_pos - lsb_pos + 1)) - 1) << lsb_pos;
	uint32_t registerValue = this->getRegister(afe, registerAddr);
	uint32_t value = (registerValue & mask) >> lsb_pos;

	return value;
}

void Afe::updateAfeRegDict(const uint32_t& afe, std::unordered_map<uint32_t, uint32_t> &dict, const std::string& functionName){

	auto afe_funct_it = this->afeFunctionDict.find(functionName);
	if (afe_funct_it == this->afeFunctionDict.end()) {
		throw std::invalid_argument("AFE function name " + functionName + " not found in the AFE functions dictionary.");
	}

	const Afe::BitField& bit_field = afe_funct_it->second;
	const auto& registerAddr = bit_field.begin()->first;
	uint32_t registerValue = this->getRegister(afe, registerAddr);

	auto regDict_it = dict.find(registerAddr);
	if (regDict_it == dict.end()) {
		throw std::invalid_argument("Internal Error: AFE function name " + functionName + " has an invalid register address: "+ std::to_string(registerAddr) +".");
	}
	regDict_it->second = registerValue;

}

uint32_t Afe::getAFEFunctionValueFromRegDict(const uint32_t& afe, std::unordered_map<uint32_t, uint32_t> &dict, const std::string& functionName){

	auto afe_funct_it = this->afeFunctionDict.find(functionName);
	if (afe_funct_it == this->afeFunctionDict.end()) {
		throw std::invalid_argument("AFE function name " + functionName + " not found in the AFE functions dictionary.");
	}

	const Afe::BitField& bit_field = afe_funct_it->second;
	const auto& registerAddr = bit_field.begin()->first;
	const auto& msb_pos = bit_field.begin()->second.first;
	const auto& lsb_pos = bit_field.begin()->second.second;
	uint32_t mask = ((1 << (msb_pos - lsb_pos + 1)) - 1) << lsb_pos;

	auto regDict_it = dict.find(registerAddr);
	if (regDict_it == dict.end()) {
		throw std::invalid_argument("Internal Error: AFE function name " + functionName + " has an invalid register address: "+ std::to_string(registerAddr) +".");
	}
	uint32_t registerValue = regDict_it->second;
	uint32_t value = (registerValue & mask) >> lsb_pos;

	return value;
}