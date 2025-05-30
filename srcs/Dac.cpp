#include "Dac.hpp"

Dac::Dac()
	: spi(std::make_unique<Spi>()){
   
	std::unordered_map<uint32_t, uint32_t> channelValues = {
        {0, 0},
        {1, 0},
        {2, 0},
        {3, 0},
        {4, 0},
        {5, 0},
        {6, 0},
        {7, 0},
    };	
	this->channelValues = {
		{"afeDacTrim_0", channelValues},
		{"afeDacTrim_1", channelValues},
		{"afeDacTrim_2", channelValues},
		{"afeDacTrim_3", channelValues},
		{"afeDacTrim_4", channelValues},
		{"afeDacOffset_0", channelValues},
		{"afeDacOffset_1", channelValues},
		{"afeDacOffset_2", channelValues},
		{"afeDacOffset_3", channelValues},
		{"afeDacOffset_4", channelValues}
	};	
}

Dac::~Dac(){}

bool Dac::isBusy(){

	return this->spi->getFpgaReg()->getBits("dacGainBiasControl", "BUSY");
}

bool Dac::waitNotBusy(const double& timeout){

	auto t0 = std::chrono::high_resolution_clock::now();

	while(true){
		if(!this->isBusy()){
			break;
		}

		std::this_thread::sleep_for(std::chrono::microseconds(10));

		auto t1 = std::chrono::high_resolution_clock::now();
		std::chrono::duration<double> elapsed = t1 - t0;

		if(elapsed.count() > timeout){
			throw std::runtime_error("Timeout while waiting DAC write");
		}
	}
	return 0;
}

uint32_t Dac::triggerWrite(){

	this->spi->getFpgaReg()->setBits("dacGainBiasControl", "GO", 1);
	return this->spi->getFpgaReg()->setBits("dacGainBiasControl", "GO", 0);
}

uint32_t Dac::setDacGeneral(const std::string& chip, const uint32_t& channel, const bool& gain, const bool& buffer, const uint32_t& value){

	this->waitNotBusy();
	this->spi->getFpgaReg()->setBits("dacGainBias" + chip, "CHANNEL", (uint32_t)channel);
    this->spi->getFpgaReg()->setBits("dacGainBias" + chip, "GAIN", (uint32_t)gain);
    this->spi->getFpgaReg()->setBits("dacGainBias" + chip, "BUFFER", (uint32_t)buffer);
    uint32_t returnedValue = this->spi->getFpgaReg()->setBits("dacGainBias" + chip, "DATA", value);
	this->triggerWrite();
	this->waitNotBusy();
	return returnedValue;
}

uint32_t Dac::setDacGainBias(const std::string& what, const uint32_t& afe, const uint32_t& value){

	std::string chip = "";
	uint32_t channel = 0;
	bool gain = false;
	bool buffer =  false;
	if(what == "gain"){
		chip = std::get<0>(this->GAIN_MAPPING[afe]);
        channel = std::get<1>(this->GAIN_MAPPING[afe]);
        gain = std::get<2>(this->GAIN_MAPPING[afe]);
        buffer = std::get<3>(this->GAIN_MAPPING[afe]);
	}else if(what == "bias"){
		chip = std::get<0>(this->BIAS_MAPPING[afe]);
        channel = std::get<1>(this->BIAS_MAPPING[afe]);
        gain = std::get<2>(this->BIAS_MAPPING[afe]);
        buffer = std::get<3>(this->BIAS_MAPPING[afe]);
	}
	this->setDacGeneral(chip, channel, gain, buffer, value);
	return 0;
}

uint32_t Dac::setDacGain(const uint32_t& afe, const uint32_t& value){

	return this->setDacGainBias("gain", afe, value);
}

uint32_t Dac::setDacBias(const uint32_t& afe, const uint32_t& value){

	return this->setDacGainBias("bias", afe, value);
}

uint32_t Dac::setDacHvBias(const uint32_t& value, const bool& gain, const bool& buffer){ // VBIAS_CTRL

	return this->setDacGeneral("U5", 2, gain, buffer, value);
}

uint32_t Dac::setBiasEnable(const bool &enable){
	
	return this->spi->getFpgaReg()->setBits("biasEnable", "ENABLE", (uint32_t)enable);
}

uint32_t Dac::findCompanionChannelValue(const uint32_t& ch){
	std::string chPos = std::get<0>(this->CHANNEL_MAPPING[ch]);
    uint32_t chCh = std::get<1>(this->CHANNEL_MAPPING[ch]);
    std::string tmpPos = "";
    uint32_t tmpCh = 0;
    uint32_t compCh = 0;
    for(auto tmpMap : this->CHANNEL_MAPPING){
    	tmpPos = std::get<0>(tmpMap.second);
    	tmpCh = std::get<1>(tmpMap.second);
    	compCh = tmpMap.first;
    	if(tmpPos != chPos && tmpCh == chCh){
            break;
    	}
    }
    return compCh;
}

uint32_t Dac::setDacTrim(const uint32_t& afe, const uint32_t& ch, const uint32_t& value, const bool& gain, const bool& buffer){

	std::string register_ = "afeDacTrim_" + std::to_string(afe);
	return this->updateCurrentRegister(register_, ch, value, gain, buffer);
}

uint32_t Dac::setDacOffset(const uint32_t& afe, const uint32_t& ch, const uint32_t& value, const bool& gain, const bool& buffer){

	std::string register_ = "afeDacOffset_" + std::to_string(afe);
	return this->updateCurrentRegister(register_, ch, value, gain, buffer);
}

uint32_t Dac::setDacTrimOffset(const std::string& what, const uint32_t& afe,const uint32_t& channelH,const uint32_t& valueH,const uint32_t& channelL,const uint32_t& valueL, const bool& gain, const bool& buffer){

	std::string register_ = "afeDac" + what + "_" + std::to_string(afe);
    uint32_t valueH_ = (channelH & 0x3) << 14 | gain << 13 | buffer << 12 | valueH & 0xFFF;
    uint32_t valueL_ = (channelL & 0x3) << 14 | gain << 13 | buffer << 12 | valueL & 0xFFF;
    uint32_t value = (valueH & 0xFFFF) << 16 | (valueL & 0xFFFF);
	return this->spi->setData(register_, value);
}

uint32_t Dac::updateCurrentRegister(const std::string& reg_name, const uint32_t& ch, const uint32_t& value, const bool& gain, const bool& buffer){
	
	//this is not valid because there is no readback from the DAC registers, they always return 0.
    //It is better to save the last programed value and then update it here
	//uint32_t configuredData = this->spi->getData(reg_name); // this is always returning zero
	const auto &register_values_it = this->channelValues.find(reg_name);
	if (register_values_it == this->channelValues.end()) {
		throw std::invalid_argument("Register " + reg_name + " not found in the DAC register values dictionary.");
		return 0;
	}
    auto &register_channel_values_dict = register_values_it->second;
    uint32_t compCh = this->findCompanionChannelValue(ch);
    const auto &channel_value_it = register_channel_values_dict.find(ch);
	if (channel_value_it == register_channel_values_dict.end()) {
		throw std::invalid_argument("Channel " + std::to_string(ch) + " not found in the DAC Channel values dictionary.");
		return 0;
	}
	const auto &comp_channel_value_it = register_channel_values_dict.find(compCh);
	if (comp_channel_value_it == register_channel_values_dict.end()) {
		throw std::invalid_argument("Companion channel " + std::to_string(compCh) + " of channel" + std::to_string(ch) 
		                             + " not found in the DAC Channel values dictionary.");
		return 0;
	}

	auto compMap = this->CHANNEL_MAPPING[compCh];
	std::string compChPos = std::get<0>(compMap);
	uint32_t compChipCh = std::get<1>(compMap);
	auto chMap = this->CHANNEL_MAPPING[ch];
	std::string chPos = std::get<0>(chMap);
	uint32_t chipCh = std::get<1>(chMap);
	uint32_t dataToWrite = 0;
	uint32_t compData = (comp_channel_value_it->second & 0xFFFF);
	uint32_t chData = (chipCh & 0x3) << 14 | gain << 13 | buffer << 12 | value & 0xFFF;
	channel_value_it->second = chData;
	if(compChPos == "L"){
		dataToWrite = (chData & 0xFFFF) << 16 | (compData & 0xFFFF);
	}else if(compChPos == "H"){
		dataToWrite = (compData & 0xFFFF) << 16 | (chData & 0xFFFF);
	}else{
		throw std::runtime_error("Runtime error: undefined data position. " + std::string(__PRETTY_FUNCTION__));
	}

	return this->spi->setData(reg_name, dataToWrite);
}

