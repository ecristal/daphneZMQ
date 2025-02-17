#include "FrontEnd.hpp"

FrontEnd::FrontEnd()
	: fpgaReg(std::make_unique<FpgaReg>()){}

FrontEnd::~FrontEnd(){}

uint32_t FrontEnd::doResetDelayCtrl(){

	this->fpgaReg->setBits("frontendControl", "DELAYCTRL_RESET", 1);
    return this->fpgaReg->setBits("frontendControl", "DELAYCTRL_RESET", 0);
}

uint32_t FrontEnd::doResetSerDesCtrl(){

	this->fpgaReg->setBits("frontendControl", "SERDES_RESET", 1);
    return this->fpgaReg->setBits("frontendControl", "SERDES_RESET", 0);
}

uint32_t FrontEnd::setEnableDelayVtc(const uint32_t& value){

	return this->fpgaReg->setBits("frontendControl", "DELAY_EN_VTC", value);
}

uint32_t FrontEnd::getEnableDelayVtc(){

	return this->fpgaReg->getBits("frontendControl", "DELAY_EN_VTC");
}

uint32_t FrontEnd::getDelayCtrlReady(){

	return this->fpgaReg->getBits("frontendStatus", "DELAYCTRL_READY");
}

uint32_t FrontEnd::doTrigger(){

	return this->fpgaReg->setBits("frontendTrigger", "GO", 1);
}

uint32_t FrontEnd::setDelay(const uint8_t& afe,const uint32_t& delay){

	return this->fpgaReg->setBits("frontendDelay_" + std::to_string(afe), "DELAY", delay);
}

uint32_t FrontEnd::getDelay(const uint8_t& afe){

	return this->fpgaReg->getBits("frontendDelay_" + std::to_string(afe), "DELAY");
}

uint32_t FrontEnd::setBitslip(const uint8_t& afe,const uint32_t& bitslip){

	return this->fpgaReg->setBits("frontendBitslip_" + std::to_string(afe), "BITSLIP", bitslip);
}

uint32_t FrontEnd::getBitslip(const uint8_t& afe){

	return this->fpgaReg->getBits("frontendBitslip_" + std::to_string(afe), "BITSLIP");
}