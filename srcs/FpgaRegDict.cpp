#include "FpgaRegDict.hpp"

FpgaRegDict::FpgaRegDict(){

	BitField afeGlobalControl_bits = {
            {"RESET", {0, 0}},
            {"POWERSTATE", {1, 1}},
            {"BUSY", {2, 4}},
            {"BUSY_AFE0", {2, 2}},
            {"BUSY_AFE12", {3, 3}},
            {"BUSY_AFE34", {4, 4}}
        };

    this->fpgaRegDict["afeGlobalControl"] = {0x0000000, afeGlobalControl_bits};
    
    BitField afeControl_bits = {
    		{"DATA", {0,23}}
    };
    BitField afeDacTrim_bits = {
    		{"DATA", {0,31}}
    };
    BitField afeDacOffset_bits = {
    		{"DATA", {0,31}}
    };

    for(int afe = 0; afe < 5; afe++){
    	uint32_t offset = afe * 0xC;
        this->fpgaRegDict["afeControl_" + std::to_string(afe)] = {0x00000004 + offset, afeControl_bits};
        this->fpgaRegDict["afeDacTrim_" + std::to_string(afe)] = {0x00000008 + offset, afeDacTrim_bits};
        this->fpgaRegDict["afeDacOffset_" + std::to_string(afe)] = {0x0000000C + offset, afeDacOffset_bits};
    }

    BitField dacGainBiasControl_bits = {
            {"BUSY", {0, 0}}
        };
    BitField dacGainBias_bits = {
        {"DATA", {0, 11}},
        {"BUFFER", {12, 12}},
        {"GAIN", {13, 13}},
        {"CHANNEL", {14, 15}}
    };

    this->fpgaRegDict["dacGainBiasControl"] = {0xC000000, dacGainBiasControl_bits};
    this->fpgaRegDict["dacGainBiasU50"] = {0xC000004, dacGainBias_bits};
    this->fpgaRegDict["dacGainBiasU53"] = {0xC000008, dacGainBias_bits};
    this->fpgaRegDict["dacGainBiasU5"] = {0xC00000C, dacGainBias_bits};

    BitField spyBuffer_bits = {
        {"DATA", {0, 15}},
        {"DATAL", {2, 15}},
        {"DATAH", {18, 31}}
    };

    for (int afe = 0; afe < 5; ++afe) {
        uint32_t offsetAfe = afe * 0x9000;
        for (int ch = 0; ch < 9; ++ch) {
            uint32_t offset = offsetAfe + ch * 0x1000;
            this->fpgaRegDict["spyBuffer_" + std::to_string(afe) + "_" + std::to_string(ch)] = {0x10000000 + offset, spyBuffer_bits};
        }
    }

    BitField timestamp_bits = {
        {"VALUE", {0, 15}}
    };

    this->fpgaRegDict["timestamp0"] = {0x1002D000, timestamp_bits};
    this->fpgaRegDict["timestamp1"] = {0x1002E000, timestamp_bits};
    this->fpgaRegDict["timestamp2"] = {0x1002F000, timestamp_bits};
    this->fpgaRegDict["timestamp3"] = {0x10030000, timestamp_bits};

    BitField endpointClockControl_bits = {
        {"MMCM0_RESET", {0, 0}},
        {"MMCM1_RESET", {1, 1}},
        // Compatibility aliases used by Endpoint and existing clients.
        {"SOFT_RESET", {0, 0}},
        {"MMCM_RESET", {1, 1}},
        {"CLOCK_SOURCE", {2, 2}}
    };

    BitField endpointClockStatus_bits = {
    	{"MMCM0_LOCKED", {0, 0}},
        {"MMCM1_LOCKED", {1, 1}}
    };

    BitField endpointControl_bits = {
    	{"RESET", {16, 16}},
        {"ADDRESS", {0, 15}}
    };

    BitField endpointStatus_bits = {
    	{"TIMESTAMP_OK", {4, 4}},
    	{"FSM_STATUS", {0, 3}}
    };

    this->fpgaRegDict["endpointClockControl"] = {0x4000000, endpointClockControl_bits};
    this->fpgaRegDict["endpointClockStatus"] = {0x4000004, endpointClockStatus_bits};
    this->fpgaRegDict["endpointControl"] = {0x4000008, endpointControl_bits};
    this->fpgaRegDict["endpointStatus"] = {0x400000C, endpointStatus_bits};

    BitField frontendControl_bits = {
        {"DELAY_EN_VTC", {2, 2}},
        {"SERDES_RESET", {1, 1}},
        {"DELAYCTRL_RESET", {0, 0}}
    };

    BitField frontendStatus_bits = {
        {"DELAYCTRL_READY", {0, 0}}
    };

    BitField frontendTrigger_bits = {
        {"GO", {0, 0}}
    };

    BitField frontendDelay_bits = {
        {"DELAY", {0, 8}}
    };

    BitField frontendBitslip_bits = {
        {"BITSLIP", {0, 3}}
    };

    this->fpgaRegDict["frontendControl"] = {0x8000000, frontendControl_bits};
    this->fpgaRegDict["frontendStatus"] = {0x8000004, frontendStatus_bits};
    this->fpgaRegDict["frontendTrigger"] = {0x8000008, frontendTrigger_bits};

    for (int afe = 0; afe < 5; ++afe) {
        uint32_t offset = afe * 0x4;
        this->fpgaRegDict["frontendDelay_" + std::to_string(afe)] = {0x800000C + offset, frontendDelay_bits};
        this->fpgaRegDict["frontendBitslip_" + std::to_string(afe)] = {0x8000020 + offset, frontendBitslip_bits};
    }

    BitField tenGigabitSender_bits = {
        {"DATA", {0, 31}}
    };

    this->fpgaRegDict["tenGigabitSender"] = {0x18000000, tenGigabitSender_bits};

    BitField fanControl_bits = {
        {"FAN_CTRL", {0, 7}}
    };

    BitField fanReadSpeed_bits = {
        {"SPEED", {0, 11}}
    };

    this->fpgaRegDict["fanControl"] = {0x14000000, fanControl_bits};
    this->fpgaRegDict["fanReadSpeed_0"] = {0x14000004, fanReadSpeed_bits};
    this->fpgaRegDict["fanReadSpeed_1"] = {0x14000008, fanReadSpeed_bits};

    BitField biasEnable_bits = {
        {"ENABLE", {0, 0}}
    };
    
    this->fpgaRegDict["biasEnable"] = {0x1400000C, biasEnable_bits};
	
	BitField muxEnable_bits = {
        {"ENABLE0", {0, 0}},
        {"ENABLE1", {1, 1}}
    };

    BitField muxAddress_bits = {
        {"ADDRESS", {0, 1}}
    };

    this->fpgaRegDict["muxEnable"] = {0x14000010, muxEnable_bits};
    this->fpgaRegDict["muxAddress"] = {0x14000014, muxAddress_bits};

    BitField led_bits = {
        {"LED", {0, 5}}
    };

    this->fpgaRegDict["LED"] = {0x14000018, led_bits};

    BitField gitCommit_bits = {
        {"GIT", {0, 27}}
    };

    this->fpgaRegDict["GIT"] = {0x1400001C, gitCommit_bits};

    BitField triggerEnableLow_bits = {
        {"DATA", {0, 31}}
    };

    BitField triggerEnableHigh_bits = {
        {"DATA", {0, 7}}
    };

    this->fpgaRegDict["triggerEnableLow"] = {0x14000020, triggerEnableLow_bits};
    this->fpgaRegDict["triggerEnableHigh"] = {0x14000024, triggerEnableHigh_bits};

    BitField adHocTriggerCommand_bits = {
        {"VALUE", {0, 7}}
    };

    this->fpgaRegDict["adHocTriggerCommand"] = {0x14000028, adHocTriggerCommand_bits};

    BitField selfTriggerConfig_bits = {
        {"VALUE", {0, 13}},
        {"MAIN_DETECTION_MODE", {4, 4}},
        {"ALLOW_TRIGGER_BETWEEN_FRAMES", {5, 5}},
        {"SLOPE_CALCULATION_THREE_SAMPLES", {6, 6}},
        {"SLOPE_THRESHOLD", {7, 13}}
    };

    BitField selfTriggerSignalDelay_bits = {
        {"DELAY", {0, 4}}
    };

    BitField selfTriggerFilterOutputSelector_bits = {
        {"SELECTOR", {0, 1}}
    };

    BitField selfTriggerCounterReset_bits = {
        {"RESET", {0, 0}}
    };

    this->fpgaRegDict["selfTriggerConfig"] = {0x1400002C, selfTriggerConfig_bits};
    this->fpgaRegDict["selfTriggerSignalDelay"] = {0x14000030, selfTriggerSignalDelay_bits};
    this->fpgaRegDict["selfTriggerFilterOutputSelector"] = {0x14000034, selfTriggerFilterOutputSelector_bits};
    this->fpgaRegDict["selfTriggerCounterReset"] = {0x14000038, selfTriggerCounterReset_bits};
    this->fpgaRegDict["selfTriggerCompensatorEnableLow"] = {0x1400003C, triggerEnableLow_bits};
    this->fpgaRegDict["selfTriggerCompensatorEnableHigh"] = {0x14000040, triggerEnableHigh_bits};
    this->fpgaRegDict["selfTriggerInvertEnableLow"] = {0x14000044, triggerEnableLow_bits};
    this->fpgaRegDict["selfTriggerInvertEnableHigh"] = {0x14000048, triggerEnableHigh_bits};

    BitField spyTriggerControl_bits = {
        {"CONTROL", {0, 2}},
        {"SOURCE", {0, 1}},
        {"INHIBIT", {2, 2}}
    };

    this->fpgaRegDict["spyTriggerControl"] = {0x08000034, spyTriggerControl_bits};

    BitField outputSpyBufferStatus_bits = {
        {"STREAM_SELECT", {0, 2}},
        {"FSM_STATUS", {28, 31}}
    };

    BitField registerData_bits = {
        {"DATA", {0, 31}}
    };

    this->fpgaRegDict["outputSpyBufferStatus"] = {0x20000000, outputSpyBufferStatus_bits};
    this->fpgaRegDict["outputSpyBufferData"] = {0x20000004, registerData_bits};

    BitField selfTriggerThreshold_bits = {
        {"THRESHOLD", {0, 27}}
    };

    for (int channel = 0; channel < 40; ++channel) {
        const uint32_t offset = static_cast<uint32_t>(channel) * 0x20;
        const std::string suffix = "_" + std::to_string(channel);

        this->fpgaRegDict["selfTriggerThreshold" + suffix] =
            {0x20010000 + offset, selfTriggerThreshold_bits};
        this->fpgaRegDict["selfTriggerRecordCountLow" + suffix] =
            {0x20010004 + offset, registerData_bits};
        this->fpgaRegDict["selfTriggerRecordCountHigh" + suffix] =
            {0x20010008 + offset, registerData_bits};
        this->fpgaRegDict["selfTriggerBusyCountLow" + suffix] =
            {0x2001000C + offset, registerData_bits};
        this->fpgaRegDict["selfTriggerBusyCountHigh" + suffix] =
            {0x20010010 + offset, registerData_bits};
        this->fpgaRegDict["selfTriggerFullCountLow" + suffix] =
            {0x20010014 + offset, registerData_bits};
        this->fpgaRegDict["selfTriggerFullCountHigh" + suffix] =
            {0x20010018 + offset, registerData_bits};
    }
}

FpgaRegDict::~FpgaRegDict(){}

void FpgaRegDict::print() const {

    for (const auto& reg : fpgaRegDict) {
        std::cout << "Register: " << reg.first << ", Address: 0x" 
                  << std::hex << reg.second.first << std::endl;

        for (const auto& bit : reg.second.second) {
            std::cout << "  Bit Name: " << bit.first << ", Range: " 
                      << bit.second.first << "-" << bit.second.second << std::endl;
        }
    }
}

bool FpgaRegDict::hasKey(const std::string& key) const {
	return this->fpgaRegDict.find(key) != this->fpgaRegDict.end();
}
