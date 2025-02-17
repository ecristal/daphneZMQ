#include "Daphne.hpp"

Daphne::Daphne()
	: afe(std::make_unique<Afe>()),
	  dac(std::make_unique<Dac>()),
	  frontend(std::make_unique<FrontEnd>()),
	  spyBuffer(std::make_unique<SpyBuffer>()){}

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
	uint32_t currentLength = 0;
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

	std::cout << "Scanning " + what << std::endl;
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
	uint32_t firstDelay = 0;
	uint32_t lastDelay = 0;
	if(delays.has_value()){
		firstDelay = delays.value().first;
		lastDelay = delays.value().second;
	}else{
		throw std::runtime_error("No delays available!");
	}
	uint32_t bestDelay = (uint32_t)(firstDelay + (lastDelay - firstDelay) / 2);
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
												   "delay",
												    bitslipTaps,
												    [this](const uint32_t& a, const uint32_t& b) { return this->frontend->setBitslip(a, b);}
												    );
	int bestBitslip = this->findIndex(data, (uint32_t)0x00FF);
	if(bestBitslip == -1)
		return 0;
		//throw std::runtime_error("Failed to find best bitslip");
	std::cout << "Optimun bitslip: 0x" << std::hex << bestBitslip << std::endl;
	this->frontend->setBitslip(afe, (uint32_t)bestBitslip);
	this->frontend->doTrigger();
	uint32_t value = this->spyBuffer->getFrameClock(afe, 8);
	std::cout << "Read opt bitslip: 0x" << std::hex << value << std::endl;
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