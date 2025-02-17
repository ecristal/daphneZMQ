#ifndef FPGAREGDICT_HPP
#define FPGAREGDICT_HPP

#include <iostream>
#include <unordered_map>
#include <string>
#include <vector>

class FpgaRegDict {
public:
    // Constructor
    using BitField = std::unordered_map<std::string, std::pair<int, int>>;
    using RegisterMap = std::unordered_map<std::string, std::pair<uint32_t, BitField>>;

    FpgaRegDict();

    // Destructor
    ~FpgaRegDict();

    void print() const;
    bool hasKey(const std::string & key) const;
    const RegisterMap& getRegisterMap() const {return this->fpgaRegDict;}

private:
     RegisterMap fpgaRegDict;

     void createDict();
};

#endif // FPGAREGDICT_HPP