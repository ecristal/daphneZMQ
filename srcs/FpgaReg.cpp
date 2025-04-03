#include "reg.hpp"
#include "FpgaRegDict.hpp"
#include "FpgaReg.hpp"

FpgaReg::FpgaReg()
	: baseAddr(0x80000000),
	memLen(0x7FFFFFFF),
	fpgaMem(std::make_unique<reg>(this->baseAddr, this->memLen, this->fpgaRegDict)){}

FpgaReg::~FpgaReg(){}

uint32_t FpgaReg::setBits(const std::string &regName, const std::string &bitName, const uint32_t &Data){

	uint32_t bitsWritten = this->fpgaMem->WriteBits(regName,bitName, Data);
	if(bitsWritten != Data){
		throw std::runtime_error("Error writting register here: \n" + std::string(__PRETTY_FUNCTION__));
	}else{
		return bitsWritten;
	}
}

uint32_t FpgaReg::getBits(const std::string &regName, const std::string &bitName, const uint32_t &offset){
	uint32_t offset_ = offset*(sizeof(uint32_t));
	return this->fpgaMem->ReadBits(regName, bitName, offset_);
}
