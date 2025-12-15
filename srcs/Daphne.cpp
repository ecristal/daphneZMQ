#include "Daphne.hpp"
#include <sstream>
#include <thread>
#include <chrono>

Daphne::Daphne()
	: afe(std::make_unique<Afe>()),
	  dac(std::make_unique<Dac>()),
	  frontend(std::make_unique<FrontEnd>()),
	  spyBuffer(std::make_unique<SpyBuffer>())
	{
		this->initRegDictHistory();

		try {
			hdmezzdriver = std::make_unique<I2CMezzDrivers::HDMezzDriver>();
		} catch (const std::exception &e) {
			std::cerr << "Warning: HDMezzDriver unavailable: " << e.what() << std::endl;
			hdmezzdriver.reset();
		}

		try {
			regulatorsdriver = std::make_unique<I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver>();
		} catch (const std::exception &e) {
			std::cerr << "Warning: regulators driver unavailable: " << e.what() << std::endl;
			regulatorsdriver.reset();
		}

		try {
			current_monitor = std::make_unique<CurrentMonitorDrivers::CurrentMonitor>();
		} catch (const std::exception &e) {
			std::cerr << "Warning: current monitor unavailable: " << e.what() << std::endl;
			current_monitor.reset();
		}

		try {
			ads7138driver_addr_0x10 = std::make_unique<I2CADCsDrivers::ADS7138_Driver>(0x10);
			ads7138driver_addr_0x10->setEnabledChannels({true, true, true, true,
			                                            true, true, true, false});
		} catch (const std::exception &e) {
			std::cerr << "Warning: ADS7138 (0x10) unavailable: " << e.what() << std::endl;
			ads7138driver_addr_0x10.reset();
		}
		try {
			ads7138driver_addr_0x17 = std::make_unique<I2CADCsDrivers::ADS7138_Driver>(0x17);
			ads7138driver_addr_0x17->setEnabledChannels({false, false, true, false,
			                                            false, true, false, true});
		} catch (const std::exception &e) {
			std::cerr << "Warning: ADS7138 (0x17) unavailable: " << e.what() << std::endl;
			ads7138driver_addr_0x17.reset();
		}
		this->isI2C_1_device_configuring.store(false);
		this->isI2C_2_device_configuring.store(false);
		this->user_vbias_voltage_request.store(false);
		this->is_vbias_voltage_monitor_reading.store(false);
		this->HDMezz_5V_voltage_afe4.store(0.0);
		this->HDMezz_5V_current_afe4.store(0.0);
		this->HDMezz_3V3_voltage_afe4.store(0.0);
		this->HDMezz_3V3_current_afe4.store(0.0);
		this->HDMezz_5V_power_afe4.store(0.0);
		this->HDMezz_3V3_power_afe4.store(0.0);

		this->HDMezz_5V_voltage_afe3.store(0.0);
		this->HDMezz_5V_current_afe3.store(0.0);
		this->HDMezz_3V3_voltage_afe3.store(0.0);
		this->HDMezz_3V3_current_afe3.store(0.0);
		this->HDMezz_5V_power_afe3.store(0.0);
		this->HDMezz_3V3_power_afe3.store(0.0);

		this->HDMezz_5V_voltage_afe2.store(0.0);
		this->HDMezz_5V_current_afe2.store(0.0);
		this->HDMezz_3V3_voltage_afe2.store(0.0);
		this->HDMezz_3V3_current_afe2.store(0.0);
		this->HDMezz_5V_power_afe2.store(0.0);
		this->HDMezz_3V3_power_afe2.store(0.0);

		this->HDMezz_5V_voltage_afe1.store(0.0);
		this->HDMezz_5V_current_afe1.store(0.0);
		this->HDMezz_3V3_voltage_afe1.store(0.0);
		this->HDMezz_3V3_current_afe1.store(0.0);
		this->HDMezz_5V_power_afe1.store(0.0);
		this->HDMezz_3V3_power_afe1.store(0.0);

		this->HDMezz_5V_voltage_afe0.store(0.0);
		this->HDMezz_5V_current_afe0.store(0.0);
		this->HDMezz_3V3_voltage_afe0.store(0.0);
		this->HDMezz_3V3_current_afe0.store(0.0);
		this->HDMezz_5V_power_afe0.store(0.0);
		this->HDMezz_3V3_power_afe0.store(0.0);
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

I2CMezzDrivers::HDMezzDriver* Daphne::getHDMezzDriver(){

	return this->hdmezzdriver.get();
}

I2CRegulatorsDrivers::PJT004A0X43_SRZ_Driver* Daphne::getRegulatorsDriver(){

	return this->regulatorsdriver.get();
}

I2CADCsDrivers::ADS7138_Driver* Daphne::getADS7138_Driver_addr_0x10(){

	return this->ads7138driver_addr_0x10.get();
}

I2CADCsDrivers::ADS7138_Driver* Daphne::getADS7138_Driver_addr_0x17(){
	return this->ads7138driver_addr_0x17.get();
}

CurrentMonitorDrivers::CurrentMonitor* Daphne::getCurrentMonitorDriver(){
	return this->current_monitor.get();
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
		// Allow snapshot to latch before reading; 1 ms matches the stable case observed
		std::this_thread::sleep_for(std::chrono::milliseconds(1));
		data[i] = this->spyBuffer->getFrameClock(afe, 0);
		//std::cout << what << ": 0x" << std::hex << i << " - 0x" << std::hex << data[i] << std::endl;
	}

	return data;
}

uint32_t Daphne::setBestDelay(const uint32_t& afe, const size_t& delayTaps, std::string* debug_out){

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

	if (debug_out) {
		std::ostringstream os;
		os << "  DELAY_SCAN window " << static_cast<uint32_t>(firstDelay)
		   << ".." << static_cast<uint32_t>(lastDelay)
		   << " (len=" << static_cast<uint32_t>(lastDelay - firstDelay + 1)
		   << "), sample=0, word=0x" << std::hex << data[static_cast<size_t>(firstDelay)]
		   << std::dec << ", best=" << bestDelay << "\n";
		*debug_out = os.str();
	}

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

uint32_t Daphne::setBestBitslip(const uint32_t& afe, const size_t& bitslipTaps, std::string* debug_out){

	const uint32_t initialBitslip = this->frontend->getBitslip(afe);

	std::vector<uint32_t> data = this->scanGeneric( afe,
												   "bitslip",
												    bitslipTaps,
												    [this](const uint32_t& a, const uint32_t& b) { return this->frontend->setBitslip(a, b);}
												    );

	auto it = std::find_if(data.begin(), data.end(), [](uint32_t word) {
		constexpr uint32_t kTarget32 = 0x00FF00FFu;
		return word == kTarget32;
	});
	int bestBitslip = (it != data.end()) ? static_cast<int>(std::distance(data.begin(), it)) : -1;

	uint32_t finalBitslip = initialBitslip;
	if (bestBitslip >= 0) {
		finalBitslip = static_cast<uint32_t>(bestBitslip);
	} else {
		std::cerr << "Warning: setBestBitslip could not find expected pattern for AFE "
		          << afe << "; restoring bitslip to " << initialBitslip << std::endl;
	}

	if (debug_out) {
		std::ostringstream os;
		os << "  BITSLIP_SCAN (sample=0, expect 0x00FF00FF):";
		for (size_t i = 0; i < data.size(); ++i) {
			os << " [" << i << "]=0x" << std::hex << std::uppercase << data[i];
		}
		os << std::dec << "\n  chosen=" << finalBitslip << " (initial " << initialBitslip << ")\n";
		*debug_out = os.str();
	}

	this->frontend->setBitslip(afe, finalBitslip);
	this->frontend->doTrigger();
	uint32_t value = this->spyBuffer->getFrameClock(afe, 0);
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

	static const std::vector<uint32_t> kAfeRegisterList = {
	    0,  1,  2,  3,  4,  5,  10, 13, 15, 17, 19, 21, 25, 27,
	    29, 31, 33, 50, 51, 52, 53, 54, 55, 56, 57, 59, 66,
	};

	this->afe->setRegisterList(kAfeRegisterList);

	{
		std::lock_guard<std::mutex> lock(this->state_mutex_);
		this->state_.clear();
		this->state_[{StateKey::Kind::kBiasControl, 0, 0}] = 0;
	}
}

void Daphne::setAfeRegDictValue(const uint32_t& afe, const uint32_t &regAddr, const uint32_t &regValue) {

	if (afe > 4) {
		throw std::out_of_range("AFE index " + std::to_string(afe) + " out of range. Expected range 0-4.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	this->state_[{StateKey::Kind::kAfeReg, afe, regAddr}] = regValue;
}

uint32_t Daphne::getAfeRegDictValue(const uint32_t& afe, const uint32_t &regAddr){

	if (afe > 4) {
		throw std::out_of_range("AFE index " + std::to_string(afe) + " out of range. Expected range 0-4.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	auto it = this->state_.find({StateKey::Kind::kAfeReg, afe, regAddr});
	return (it == this->state_.end()) ? 0u : it->second;
}

void Daphne::setAfeAttenuationDictValue(const uint32_t& afe, const uint32_t &attenuation) {

	if (afe > 4) {
		throw std::out_of_range("AFE index " + std::to_string(afe) + " out of range. Expected range 0-4.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	this->state_[{StateKey::Kind::kAfeAttenuation, afe, 0}] = attenuation;
}

uint32_t Daphne::getAfeAttenuationDictValue(const uint32_t& afe) {

	if (afe > 4) {
		throw std::out_of_range("AFE index " + std::to_string(afe) + " out of range. Expected range 0-4.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	auto it = this->state_.find({StateKey::Kind::kAfeAttenuation, afe, 0});
	return (it == this->state_.end()) ? 0u : it->second;
}

void Daphne::setChOffsetDictValue(const uint32_t &ch, const uint32_t &offset) {
	if (ch > 39) {
		throw std::out_of_range("Channel index " + std::to_string(ch) + " out of range. Expected range 0-39.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	this->state_[{StateKey::Kind::kChannelOffset, ch, 0}] = offset;
}

uint32_t Daphne::getChOffsetDictValue(const uint32_t& ch) {

	if (ch > 39) {
		throw std::out_of_range("Channel index " + std::to_string(ch) + " out of range. Expected range 0-39.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	auto it = this->state_.find({StateKey::Kind::kChannelOffset, ch, 0});
	return (it == this->state_.end()) ? 0u : it->second;
}

void Daphne::setChTrimDictValue(const uint32_t &ch, const uint32_t &trim) {
	if (ch > 39) {
		throw std::out_of_range("Channel index " + std::to_string(ch) + " out of range. Expected range 0-39.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	this->state_[{StateKey::Kind::kChannelTrim, ch, 0}] = trim;
}

uint32_t Daphne::getChTrimDictValue(const uint32_t& ch) {

	if (ch > 39) {
		throw std::out_of_range("Channel index " + std::to_string(ch) + " out of range. Expected range 0-39.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	auto it = this->state_.find({StateKey::Kind::kChannelTrim, ch, 0});
	return (it == this->state_.end()) ? 0u : it->second;
}

void Daphne::setBiasVoltageDictValue(const uint32_t& afe, const uint32_t &biasVoltage) {

	if (afe > 4) {
		throw std::out_of_range("AFE index " + std::to_string(afe) + " out of range. Expected range 0-4.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	this->state_[{StateKey::Kind::kBiasVoltage, afe, 0}] = biasVoltage;
}

uint32_t Daphne::getBiasVoltageDictValue(const uint32_t& afe) {

	if (afe > 4) {
		throw std::out_of_range("AFE index " + std::to_string(afe) + " out of range. Expected range 0-4.");
	}

	std::lock_guard<std::mutex> lock(this->state_mutex_);
	auto it = this->state_.find({StateKey::Kind::kBiasVoltage, afe, 0});
	return (it == this->state_.end()) ? 0u : it->second;
}

void Daphne::setBiasControlDictValue(const uint32_t& biasControl) {
	std::lock_guard<std::mutex> lock(this->state_mutex_);
	this->state_[{StateKey::Kind::kBiasControl, 0, 0}] = biasControl;
}

uint32_t Daphne::getBiasControlDictValue() {
	std::lock_guard<std::mutex> lock(this->state_mutex_);
	auto it = this->state_.find({StateKey::Kind::kBiasControl, 0, 0});
	return (it == this->state_.end()) ? 0u : it->second;
}
