#include "Daphne.hpp"

Daphne::Daphne()
	: afe(std::make_unique<Afe>()),
	  dac(std::make_unique<Dac>()),
	  frontend(std::make_unique<FrontEnd>()),
	  spyBuffer(std::make_unique<SpyBuffer>()){
		this->initRegDictHistory();
	  }

Daphne::~Daphne(){}

Afe* Daphne::getAfe(){

	return this->afe.get();
}

Dac* Daphne::getDac(){

	return this->dac.get();
}

FrontEnd* Daphne::getFrontEnd(){

	return this->frontend.get();
}

SpyBuffer* Daphne::getSpyBuffer(){

	return this->spyBuffer.get();
}

std::optional<std::pair<uint32_t, uint32_t>> Daphne::longestIdenticalSubsequenceIndices(const std::vector<uint32_t>& nums){

	if(nums.empty()){
		return std::nullopt;
	}

	uint32_t maxLength = 1;
	uint32_t maxStartIndex = 0;
	uint32_t currentLength = 1;
	uint32_t currentStartIndex = 0;

	for(int i = 1; i < nums.size(); i++){

		if(nums[i] == nums[i - 1]){

			currentLength += 1;
		}else{

			if(currentLength > maxLength){

				maxLength = currentLength;
                maxStartIndex = currentStartIndex;
			}

			currentLength = 1;
            currentStartIndex = i;
		}
	}

	if(currentLength > maxLength){

		maxLength = currentLength;
        maxStartIndex = currentStartIndex;
	}

	return std::make_pair(maxStartIndex, maxStartIndex + maxLength - 1);
}

std::vector<uint32_t> Daphne::scanGeneric(const uint32_t& afe,const std::string& what,const uint32_t& taps, std::function<uint32_t(const uint32_t&, const uint32_t&)> setFunc){

	//std::cout << "Scanning " + what << std::endl;
	std::vector<uint32_t> data(taps);
	for(uint32_t i = 0; i < taps; i++){

		setFunc(afe, i);
		this->frontend->doTrigger();
		data[i] = this->spyBuffer->getFrameClock(afe, 8);
		//std::cout << what << ": 0x" << std::hex << i << " - 0x" << std::hex << data[i] << std::endl;
	}

	return data;
}

uint32_t Daphne::setBestDelay(const uint32_t& afe, const size_t& delayTaps){

	std::vector<uint32_t> data =  this->scanGeneric( afe,
												   "delay",
												    delayTaps,
												    [this](const uint32_t& a, const uint32_t& b) { return this->frontend->setDelay(a, b);}
												    );

	std::optional<std::pair<uint32_t, uint32_t>> delays = this->longestIdenticalSubsequenceIndices(data);
	float firstDelay = 0.0;
	float lastDelay = 0.0;
	if(delays.has_value()){
		firstDelay = (float)delays.value().first;
		lastDelay = (float)delays.value().second;
	}else{
		throw std::runtime_error("No delays available!");
	}
	uint32_t bestDelay = (uint32_t)(firstDelay + ((lastDelay - firstDelay)/2.0));
	return this->frontend->setDelay(afe, bestDelay);
}

template <typename T>
int Daphne::findIndex(const std::vector<T>& data, const T& target){

	auto it = std::find(data.begin(), data.end(), target);

	if(it == data.end()){
		return -1;
	}else{
		return std::distance(data.begin(),it);
	}
}

uint32_t Daphne::setBestBitslip(const uint32_t& afe, const size_t& bitslipTaps){

	std::vector<uint32_t> data = this->scanGeneric( afe,
												   "bitslip",
												    bitslipTaps,
												    [this](const uint32_t& a, const uint32_t& b) { return this->frontend->setBitslip(a, b);}
												    );
	int bestBitslip = this->findIndex(data, (uint32_t)0x00FF);
	if(bestBitslip == -1)
		return 0;
		//throw std::runtime_error("Failed to find best bitslip");
	//std::cout << "Optimun bitslip: 0x" << std::hex << bestBitslip << std::endl;
	this->frontend->setBitslip(afe, (uint32_t)bestBitslip);
	this->frontend->doTrigger();
	uint32_t value = this->spyBuffer->getFrameClock(afe, 8);
	//std::cout << "Read opt bitslip: 0x" << std::hex << value << std::endl;
	return value;
}

double Daphne::calcInputVoltage(const double& value, const double& vGain_mV){

	double gain_dB = 0.0;
	double vCntl = vGain_mV / 1000 * 1.5 / (1.5 + 2.49);
	std::vector<double> vCntlLUT = this->AFE_GAIN_LUT["VCNTL"];
	std::vector<double> gainLUT  = this->AFE_GAIN_LUT["GAIN"];
	int idx = this->findIndex(vCntlLUT, vCntl);
	if(idx != -1){
		gain_dB = gainLUT[idx];
	}else{
		idx = std::lower_bound(vCntlLUT.begin(), vCntlLUT.end(), vCntl) - vCntlLUT.begin();
		int idxPrev = -1;
		int idxNext  = -1; 
		if(idx > 0){
			idxPrev = idx - 1;
		}
		if(idx < vCntlLUT.size()){
			idxNext = idx;
		}
		if(idxPrev == -1){
			gain_dB = gainLUT[0];
		}else if(idxNext == -1){
			gain_dB = gainLUT[gainLUT.size()-1];
		}else{
			gain_dB = ((gainLUT[idxNext] - gainLUT[idxPrev]) / (vCntlLUT[idxNext] - vCntlLUT[idxPrev]) * vCntl
                           + gainLUT[idxPrev]);
		}
	}
	double gain = std::pow(10,gain_dB / 20);
	return value / gain;
}

void Daphne::initRegDictHistory() {

	// {REGISTER_ADDR, REGISTER_VALUE}
    std::unordered_map<uint32_t, uint32_t> afeRegDict = {
        {0, 0},
        {1, 0},
        {2, 0},
        {3, 0},
        {4, 0},
        {5, 0},
        {10, 0},
        {13, 0},
        {15, 0},
        {17, 0},
        {19, 0},
        {21, 0},
        {25, 0},
        {27, 0},
        {29, 0},
        {31, 0},
        {33, 0},
        {50, 0},
        {51, 0},
        {52, 0},
        {53, 0},
        {54, 0},
        {55, 0},
        {56, 0},
        {57, 0},
        {59, 0},
        {66, 0}
    };

	std::vector<uint32_t> regList;
	for(const auto& [key, _] : afeRegDict){
		regList.push_back(key);
	}
	this->afe->setRegisterList(regList);

	std::unordered_map<uint32_t, uint32_t> stdAfeDict = {
        {0, 0},
        {1, 0},
        {2, 0},
        {3, 0},
        {4, 0}
    };

	std::unordered_map<uint32_t, uint32_t> stdChDict = {
        {0, 0},
        {1, 0},
        {2, 0},
        {3, 0},
        {4, 0},
		{5, 0},
		{6, 0},
		{7, 0},
		{8, 0},
		{9, 0},
		{10, 0},
		{11, 0},
		{12, 0},
		{13, 0},
		{14, 0},
		{15, 0},
		{16, 0},
		{17, 0},
		{18, 0},
		{19, 0},
		{20, 0},
		{21, 0},
		{22, 0},
		{23, 0},
		{24, 0},
		{25, 0},
		{26, 0},
		{27, 0},
		{28, 0},
		{29, 0},
		{30, 0},
		{31, 0},
		{32, 0},
		{33, 0},
		{34, 0},
		{35, 0},
		{36, 0},
		{37, 0},
		{38, 0},
		{39, 0}
    };

	this->afeRegDictSetting.clear();
	for(int i = 0; i < 5; i++) {
		this->afeRegDictSetting.push_back(afeRegDict);
	}
	this->afeAttenuationDictSetting.clear();
	this->afeAttenuationDictSetting = stdAfeDict;
	this->biasVoltageSetting.clear();
	this->biasVoltageSetting = stdAfeDict;
	this->biasControlSetting = 0;
	this->chOffsetDictSetting.clear();
	this->chOffsetDictSetting = stdChDict;
	this->chTrimDictSetting.clear();
	this->chTrimDictSetting = stdChDict;
}

void Daphne::setAfeRegDictValue(const uint32_t& afe, const uint32_t &regAddr, const uint32_t &regValue) {

	if(afe >= this->afeRegDictSetting.size()) {
		throw std::out_of_range("AFE index " + std::to_string(afe) +" out of range. Expected range 0-4.");
	}

	auto it = this->afeRegDictSetting[afe].find(regAddr);
	if (it != this->afeRegDictSetting[afe].end()) {
		it->second = regValue;
	} else {
		throw std::invalid_argument("Register " + std::to_string(regAddr) + " not found in the AFE register dictionary.");
	}
}

uint32_t Daphne::getAfeRegDictValue(const uint32_t& afe, const uint32_t &regAddr){

	if(afe >= this->afeRegDictSetting.size()) {
		throw std::out_of_range("AFE index " + std::to_string(afe) +" out of range. Expected range 0-4.");
	}

	auto it = this->afeRegDictSetting[afe].find(regAddr);
	if (it != this->afeRegDictSetting[afe].end()) {
		return it->second;
	} else {
		throw std::invalid_argument("Register " + std::to_string(regAddr) + " not found in the AFE register dictionary.");
		return 0;
	}
}

void Daphne::setAfeAttenuationDictValue(const uint32_t& afe, const uint32_t &attenuation) {

	auto it = this->afeAttenuationDictSetting.find(afe);
	if (it != this->afeAttenuationDictSetting.end()) {
		it->second = attenuation;
	} else {
		throw std::out_of_range("AFE index " + std::to_string(afe) +" out of range. Expected range 0-4.");
	}
}

uint32_t Daphne::getAfeAttenuationDictValue(const uint32_t& afe) {

	auto it = this->afeAttenuationDictSetting.find(afe);
	if (it != this->afeAttenuationDictSetting.end()) {
		return it->second;
	} else {
		throw std::out_of_range("AFE index " + std::to_string(afe) +" out of range. Expected range 0-4.");
		return 0;
	}
}

void Daphne::setChOffsetDictValue(const uint32_t &ch, const uint32_t &offset) {
	auto it = this->chOffsetDictSetting.find(ch);
	if (it != this->chOffsetDictSetting.end()) {
		it->second = offset;
	} else {
		throw std::out_of_range("Channel index " + std::to_string(ch) +" out of range. Expected range 0-39.");
	}
}

uint32_t Daphne::getChOffsetDictValue(const uint32_t& ch) {

	auto it = this->chOffsetDictSetting.find(ch);
	if (it != this->chOffsetDictSetting.end()) {
		return it->second;
	} else {
		throw std::out_of_range("Channel index " + std::to_string(ch) +" out of range. Expected range 0-39.");
		return 0;
	}
}

void Daphne::setChTrimDictValue(const uint32_t &ch, const uint32_t &trim) {
	auto it = this->chTrimDictSetting.find(ch);
	if (it != this->chTrimDictSetting.end()) {
		it->second = trim;
	} else {
		throw std::out_of_range("Channel index " + std::to_string(ch) +" out of range. Expected range 0-39.");
	}
}

uint32_t Daphne::getChTrimDictValue(const uint32_t& ch) {

	auto it = this->chTrimDictSetting.find(ch);
	if (it != this->chTrimDictSetting.end()) {
		return it->second;
	} else {
		throw std::out_of_range("Channel index " + std::to_string(ch) +" out of range. Expected range 0-39.");
		return 0;
	}
}

void Daphne::setBiasVoltageDictValue(const uint32_t& afe, const uint32_t &biasVoltage) {

	auto it = this->biasVoltageSetting.find(afe);
	if (it != this->biasVoltageSetting.end()) {
		it->second = biasVoltage;
	} else {
		throw std::out_of_range("AFE index " + std::to_string(afe) +" out of range. Expected range 0-4.");
	}
}

uint32_t Daphne::getBiasVoltageDictValue(const uint32_t& afe) {

	auto it = this->biasVoltageSetting.find(afe);
	if (it != this->biasVoltageSetting.end()) {
		return it->second;
	} else {
		throw std::out_of_range("AFE index " + std::to_string(afe) +" out of range. Expected range 0-4.");
		return 0;
	}
}