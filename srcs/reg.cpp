#include "reg.hpp"
#include "DevMem.hpp"
#include "FpgaRegDict.hpp"

reg::reg(uint64_t BaseAddr,  size_t MemLen, FpgaRegDict RegDict)
	: RegMem(std::make_unique<DevMem>(BaseAddr)){
	this->BaseAddr = BaseAddr;
	this->regDict = regDict;
	this->MemLen = MemLen;
	this->RegMem->map_memory(this->MemLen);
}

reg::~reg(){}

std::tuple<uint32_t,int,int> reg::GetRegister(const std::string& RegName, const std::string &BitName){
	if (this->regDict.hasKey(RegName)){
		const auto reg_ = this->regDict.getRegisterMap().find(RegName);
		//std::cout << "Found Key: " << reg_->first << " with address: 0x" << std::hex << reg_->second.first <<std::endl;
		uint32_t RegAddr = reg_->second.first;
        auto bitField = reg_->second.second;
        if(bitField.find(BitName) != bitField.end()){
        	auto foundBitField = bitField.find(BitName);
        	int BitRangeL = foundBitField->second.first;
        	int BitRangeH = foundBitField->second.second;
        	//std::cout << "Found BitName : " << BitName << " with values: BitRange Low " << foundBitField->second.first << " BitRange High " << foundBitField->second.second << std::endl;
        	return std::make_tuple(RegAddr, BitRangeH, BitRangeL);
        }else{
        	std::cout << "BitName : " << BitName << " not found." << std::endl;
        	return std::make_tuple(RegAddr, -1, -1); 
        }
	}else{
		std::cout << "RegName : " << RegName << " not found." << std::endl;;
		return std::make_tuple(0xdeadbeef, -1, -1);
	}
}

uint32_t reg::GetRegister(const std::string& RegName){
	if (this->regDict.hasKey(RegName)){
		auto reg_ = this->regDict.getRegisterMap().find(RegName);
		//std::cout << "Found Key: " << reg_->first << " with address: 0x" << std::hex << reg_->second.first <<std::endl;
		return reg_->second.first;
	}else{
		std::cout << "RegName : " << RegName << " not found." << std::endl;;
		return 0xdeadbeef;
	}
}

uint32_t reg::ReadRegister(const std::string &RegName){

	auto RegAddr = this->GetRegister(RegName);
	if(RegAddr == 0xffffffff){
		return 0xdeadbeef;
	}else{
		//this->RegMem->changeBaseAddr(RegAddr,this->MemLen);
		std::vector<uint32_t> value = this->RegMem->read(RegAddr,1);
		return value[0];
	}
}

uint32_t reg::WriteRegister(const std::string &RegName, const std::vector<uint32_t> &Value){

	auto RegAddr = this->GetRegister(RegName);
    if(RegAddr == 0xffffffff){
		return 0xdeadbeef;
	}else{
		//this->RegMem->changeBaseAddr(RegAddr,this->MemLen);
		this->RegMem->write(RegAddr,Value);
		return this->ReadRegister(RegName);
	}
}

uint32_t reg::ReadBits(const std::string &RegName, const std::string &BitName, const uint32_t &Offset){

	auto RegAddr = this->GetRegister(RegName, BitName);
	if(std::get<0>(RegAddr) == 0xdeadbeef){
		std::cout << "deadbeef" << std::endl;
		return 0xdeadbeef;
	}else{
		uint32_t RegAddr_ = std::get<0>(RegAddr);
		int BitRangeL = std::get<2>(RegAddr);
		int BitRangeH = std::get<1>(RegAddr);
		//this->RegMem->changeBaseAddr(RegAddr_ + Offset,this->MemLen);
		std::vector<uint32_t> value = this->RegMem->read(RegAddr_ + Offset, 1);
		//std::cout << "Offset: " << std::hex << Offset << "BitRangeL: " << std::dec << BitRangeL << "BitRangeH: " << BitRangeH << std::endl;
		//std::cout << "value read 1 = " << std::hex << value[0] << std::endl;
		uint32_t Mask;
		if((BitRangeH - BitRangeL + 1) == 32){ // Uknown behaviour
			Mask = 0xFFFFFFFF;
		}else{
			Mask = (1U << (BitRangeH - BitRangeL + 1)) - 1;
		}
		value[0] = (value[0] & (Mask << BitRangeL)) >> BitRangeL;
		//std::cout << "value read 2 = " << std::hex << value[0] << std::endl;
		return value[0];
	}
}


uint32_t reg::WriteBits(const std::string &RegName, const std::string &BitName, const uint32_t &Data){

	auto RegAddr = this->GetRegister(RegName, BitName);
	if(std::get<0>(RegAddr) == 0xdeadbeef){
		return 0xdeadbeef;
	}else{
		uint32_t RegAddr_ = std::get<0>(RegAddr);
		int BitRangeH = std::get<1>(RegAddr);
		int BitRangeL = std::get<2>(RegAddr);
		//this->RegMem->changeBaseAddr(RegAddr_,this->MemLen);
		std::vector<uint32_t> value = this->RegMem->read(RegAddr_, 1);
		uint32_t Mask;
		if((BitRangeH - BitRangeL + 1) == 32){
			Mask = 0xFFFFFFFF;
		}else{
			Mask = (1U << (BitRangeH - BitRangeL + 1)) - 1;
		}
		value[0] &= ~(Mask << BitRangeL);
		value[0] |= ((Data & Mask) << BitRangeL);
		this->WriteRegister(RegName,value);
        return this->ReadBits(RegName, BitName,0);
	}
}

std::unordered_map<std::string, uint32_t> reg::DumpRegisterList(const std::unordered_set<std::string> &registerNames){

	std::unordered_map<std::string, uint32_t> register_values;
    
    for (const std::string& strRegNames : registerNames){

    	auto RegAddr = this->GetRegister(strRegNames);
		if(RegAddr == 0xdeadbeef){
			register_values[strRegNames] = 0xdeadbeef;
		}else{
			uint32_t value = this->ReadRegister(strRegNames);
			register_values[strRegNames] = value;
		}
    }
    return register_values;
}

std::unordered_map<std::string, uint32_t> reg::LoadRegisterList(const std::unordered_map<std::string, uint32_t> &registers){

	std::unordered_map<std::string, uint32_t> register_values;
    
    for (const auto& strRegNames : registers){

    	auto RegAddr = this->GetRegister(strRegNames.first);
		if(RegAddr == 0xdeadbeef){
			register_values[strRegNames.first] = 0xdeadbeef;
		}else{
			std::vector<uint32_t> value(1);
			value[0] = strRegNames.second;
			uint32_t value_written = this->WriteRegister(strRegNames.first, value);
			register_values[strRegNames.first] = value_written;
		}
    }
    return register_values;
}