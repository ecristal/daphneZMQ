#ifndef REG_HPP
#define REG_HPP

#include <cstdint>
#include <string>
#include <vector>
#include <stdexcept>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <unordered_set>
#include <unordered_map>
#include <tuple>

#include "FpgaRegDict.hpp"
#include "DevMem.hpp"

struct BitFieldMeta {
    uint32_t addr;
    uint8_t low_bit;
    uint8_t high_bit;
};

class reg {
public:
    // Constructor
    reg(uint64_t BaseAddr,  size_t MemLen, FpgaRegDict RegDict);

    // Destructor
    ~reg();
    std::tuple<uint32_t, int, int> GetRegister(const std::string& RegName, const std::string &BitName);
    uint32_t GetRegister(const std::string& RegName);
    uint32_t ReadRegister(const std::string &RegName);
    uint32_t WriteRegister(const std::string &RegName, const std::vector<uint32_t> &Value);
    uint32_t ReadBits(const std::string &RegName, const std::string &BitName, const uint32_t &Offset);
    const uint32_t* getRegisterPointer(const std::string &RegName, const std::string &BitName, const uint32_t &Offset);
    uint32_t ReadBitsFast(const uint32_t &Offset, const bool& bitEndianess);
    uint32_t WriteBits(const std::string &RegName, const std::string &BitName, const uint32_t &Data);
    std::unordered_map<std::string, uint32_t> DumpRegisterList(const std::unordered_set<std::string> &registerNames);
    std::unordered_map<std::string, uint32_t> LoadRegisterList(const std::unordered_map<std::string, uint32_t> &registers);
    void GetFieldMeta(const std::string& regName);

private:
    uint64_t BaseAddr;
    BitFieldMeta bitFieldMetadata; 
    BitFieldMeta bitFieldMetadata_high, bitFieldMetadata_low;
    FpgaRegDict regDict;
    size_t MemLen;
    std::unique_ptr<DevMem> RegMem;

    
    void GetFieldMeta_(const std::string& regName, const std::string& bitName);
};

#endif // DEVMEM_HPP