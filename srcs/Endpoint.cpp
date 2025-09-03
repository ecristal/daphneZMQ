#include "Endpoint.hpp"

Endpoint::Endpoint()
	: fpgaReg(std::make_unique<FpgaReg>()){

	this->CLOCK_SOURCE_LOCAL = 0;
	this->CLOCK_SOURCE_ENDPOINT = 1;
}

Endpoint::~Endpoint(){}

uint32_t Endpoint::getClockSource(){
	return this->fpgaReg->getBits("endpointClockControl", "CLOCK_SOURCE");
}

uint32_t Endpoint::setClockSource(const uint32_t &clockSource){
	return this->fpgaReg->setBits("endpointClockControl", "CLOCK_SOURCE", clockSource);
}

uint32_t Endpoint::setClockSourceLocal(){
	return this->setClockSource(this->CLOCK_SOURCE_LOCAL);
}

uint32_t Endpoint::setClockSourceEndpoint(){
	return this->setClockSource(this->CLOCK_SOURCE_ENDPOINT);
}

uint32_t Endpoint::getMmcmReset(){
	return this->fpgaReg->getBits("endpointClockControl", "MMCM_RESET");
}

uint32_t Endpoint::setMmcmReset(const uint32_t &reset){
	return this->fpgaReg->setBits("endpointClockControl", "MMCM_RESET", reset);
}

uint32_t Endpoint::doMmcmReset(){
	this->setMmcmReset(1);
    return this->setMmcmReset(0);
}

uint32_t Endpoint::getSoftReset(){
	return this->fpgaReg->getBits("endpointClockControl", "SOFT_RESET");
}

uint32_t Endpoint::setSoftReset(const uint32_t &reset){
	return this->fpgaReg->setBits("endpointClockControl", "SOFT_RESET", reset);
} 

uint32_t Endpoint::doSoftReset(){
	this->setSoftReset(1);
    return this->setSoftReset(0);
}    

uint32_t Endpoint::getClockStatus(const uint32_t &mmcm){
	return this->fpgaReg->getBits("endpointClockStatus", "MMCM" + std::to_string(mmcm) + "_LOCKED");
}

uint32_t Endpoint::checkClockStatus(){
	uint32_t mmcm0 = this->getClockStatus(0);
    uint32_t mmcm1 = this->getClockStatus(1);
	if (mmcm0 == 1 && mmcm1 == 1){
		return 1;
	} else {
        throw std::runtime_error("MMCM clocks not locked (MMCM0:" + std::to_string(mmcm0) + 
                                 " , MMCM1:"+ std::to_string(mmcm1));
    }
}

uint32_t Endpoint::getAddress(){
	return this->fpgaReg->getBits("endpointControl", "ADDRESS");
}

uint32_t Endpoint::setAddress(const uint32_t &address){
	return this->fpgaReg->setBits("endpointControl", "ADDRESS", address);
}

uint32_t Endpoint::getReset(){
	return this->fpgaReg->getBits("endpointControl", "RESET");
}

uint32_t Endpoint::setReset(const uint32_t &reset){
	return this->fpgaReg->setBits("endpointControl", "RESET", reset);
}

uint32_t Endpoint::doReset(){
	this->setReset(1);
    return this->setReset(0);
}

uint32_t Endpoint::getTimestampOk(){
	return this->fpgaReg->getBits("endpointStatus", "TIMESTAMP_OK");
}

uint32_t Endpoint::getFsmStatus(){
	return this->fpgaReg->getBits("endpointStatus", "FSM_STATUS");
}

uint32_t Endpoint::checkEndpointStatus(const uint32_t &expTimestampOk, const uint32_t &expFsmStatus){
    uint32_t value = this->getTimestampOk();
    if(value != expTimestampOk){
        throw std::runtime_error("TIMESTAMP_OK register does not match (reg:" + std::to_string(value) + " != " + std::to_string(expTimestampOk) + ")");
    }
    value = this->getFsmStatus();
    if(value != expFsmStatus){
        throw std::runtime_error("FSM_STATUS register does not match (reg:" + std::to_string(value) + " != " + std::to_string(expFsmStatus) + ")");
    }
    return value;
}

uint32_t Endpoint::initEndpoint(const uint32_t &address, const uint32_t &clockSource){
	this->setClockSource(clockSource);
    this->doMmcmReset();
    this->checkClockStatus();
    this->setAddress(address);
    this->doReset();
    this->checkEndpointStatus();
    return 0;
}