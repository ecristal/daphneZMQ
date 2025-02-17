#include "Spi.hpp"

Spi::Spi()
	: fpgaReg(std::make_unique<FpgaReg>()){}

Spi::~Spi(){}

bool Spi::isBusy(){

	return (this->fpgaReg->getBits("afeGlobalControl", "BUSY",0) != 0);
}

bool Spi::waitNotBusy(const double& timeout){

	auto t0 = std::chrono::high_resolution_clock::now();

	while(true){
		if(!this->isBusy()){
			break;
		}

		std::this_thread::sleep_for(std::chrono::microseconds(10));

		auto t1 = std::chrono::high_resolution_clock::now();
		std::chrono::duration<double> elapsed = t1 - t0;

		if(elapsed.count() > timeout){
			throw std::runtime_error("Timeout while waiting for SPI transaction");
		}
	}
	return 0;
}

uint32_t Spi::setData(const std::string& regName, const uint32_t& value){

	this->waitNotBusy();
	uint32_t data = this->fpgaReg->setBits(regName, "DATA", value);
	this->waitNotBusy();
	return data;
}

uint32_t Spi::getData(const std::string& regName){

	this->waitNotBusy();
	uint32_t data = this->fpgaReg->getBits(regName, "DATA");
	this->waitNotBusy();
	return data;
}

FpgaReg* Spi::getFpgaReg(){

	return this->fpgaReg.get();
}