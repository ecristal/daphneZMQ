#include "Dac.hpp"

Dac::Dac()
	: spi(std::make_unique<Spi>()){}

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

	this->spi->getFpgaReg()->getBits("dacGainBiasControl", "GO", 1);
	return this->spi->getFpgaReg()->getBits("dacGainBiasControl", "GO", 0);
}

uint32_t Dac::setDacGeneral(const std::string& chip, const uint32_t& channel, const bool& gain, const bool& buffer, const uint32_t& value){

	this->waitNotBusy();
	this->spi->getFpgaReg()->setBits("dacGainBias" + chip, "CHANNEL", (uint32_t)channel);
    this->spi->getFpgaReg()->setBits("dacGainBias" + chip, "GAIN", (uint32_t)gain);
    this->spi->getFpgaReg()->setBits("dacGainBias" + chip, "BUFFER", (uint32_t)buffer);
    this->spi->getFpgaReg()->setBits("dacGainBias" + chip, "DATA", value);
	this->triggerWrite();
	this->waitNotBusy();
	return 0;
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
	
	uint32_t configuredData = this->spi->getData(reg_name);
	uint32_t compCh = this->findCompanionChannelValue(ch);
	auto compMap = this->CHANNEL_MAPPING[compCh];
	std::string compChPos = std::get<0>(compMap);
	uint32_t compChipCh = std::get<1>(compMap);
	auto chMap = this->CHANNEL_MAPPING[ch];
	std::string chPos = std::get<0>(chMap);
	uint32_t chipCh = std::get<1>(chMap);
	uint32_t dataToWrite = 0;
	uint32_t compData = 0;
	uint32_t chData = 0;
	if(compChPos == "L"){
		compData = (configuredData & 0xFFFF);
		chData = (chipCh & 0x3) << 14 | gain << 13 | buffer << 12 | value & 0xFFF;
		dataToWrite = (chData & 0xFFFF) << 16 | (compData & 0xFFFF);
	}else if(compChPos == "H"){
		compData = ((configuredData >> 16) & 0xFFFF);
		chData = (chipCh & 0x3) << 14 | gain << 13 | buffer << 12 | value & 0xFFF;
		dataToWrite = (compData & 0xFFFF) << 16 | (chData & 0xFFFF);
	}else{
		throw std::runtime_error("Runtime error: undefined data position. " + std::string(__PRETTY_FUNCTION__));
	}
	return this->spi->setData(reg_name, dataToWrite);
}

