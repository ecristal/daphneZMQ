#include <iostream>
#include <unordered_map>
#include <exception>
#include <zmq.hpp>

#include "Daphne.hpp"
#include "defines.hpp"
#include "protobuf/daphneV3_high_level_confs.pb.h"
#include "protobuf/daphneV3_low_level_confs.pb.h"

bool configureDaphne(const ConfigureRequest &requested_cfg, Daphne &daphne, std::string &response_str) {
    try{
        response_str = "Configuring Daphne with IP : " + requested_cfg.daphne_address() + "\n";
        response_str += "Setting slot : " + std::to_string(requested_cfg.slot()) + "\n";
        response_str += "Setting timeout_ms : " + std::to_string(requested_cfg.timeout_ms()) + "\n";
        response_str += "Setting biasctrl : " + std::to_string(requested_cfg.biasctrl()) + "\n";
        std::stringstream ss_conf_hex;
        ss_conf_hex << "0x" << std::hex << requested_cfg.self_trigger_threshold();
        response_str += "Setting self_trigger_threshold : " + ss_conf_hex.str() + "\n";
        ss_conf_hex.str("");
        ss_conf_hex.clear();
        ss_conf_hex << "0x" << std::hex << requested_cfg.self_trigger_xcorr();
        response_str += "Setting self_trigger_xcorr : " + ss_conf_hex.str() + "\n";
        ss_conf_hex.str("");
        ss_conf_hex.clear();
        ss_conf_hex << "0x" << std::hex << requested_cfg.tp_conf();
        response_str += "Setting tp_conf : " + ss_conf_hex.str() + "\n";
        ss_conf_hex.str("");
        ss_conf_hex.clear();
        ss_conf_hex << "0x" << std::hex << requested_cfg.compensator();
        response_str += "Setting compensator : " + ss_conf_hex.str() + "\n";
        ss_conf_hex.str("");
        ss_conf_hex.clear();
        ss_conf_hex << "0x" << std::hex << requested_cfg.inverters();
        response_str += "Setting inverters : " + ss_conf_hex.str() + "\n";
        response_str += "Setting channels:\n\n";
        for (const ChannelConfig &ch_config : requested_cfg.channels()) {
            response_str += "Channel ID : " + std::to_string(ch_config.id()) + "\n";
            response_str += "\tChannel Trim : " + std::to_string(ch_config.trim()) + "\n";
            response_str += "\tChannel Offset : " + std::to_string(ch_config.offset()) + "\n";
            response_str += "\tChannel Gain : " + std::to_string(ch_config.gain()) + "\n\n";
            daphne.getDac()->setDacTrim(ch_config.id() / 8, ch_config.id() % 8, ch_config.trim(), false, false);
            daphne.getDac()->setDacOffset(ch_config.id() / 8, ch_config.id() % 8, ch_config.offset(), false, false);
        }
        for(const AFEConfig &afe_config : requested_cfg.afes()){
            response_str += "AFE ID : " + std::to_string(afe_config.id()) + "\n";
            response_str += "AFE Attenuators : " + std::to_string(afe_config.attenuators()) + "\n";
            response_str += "AFE VBias : " + std::to_string(afe_config.v_bias()) + "\n";
            ADCConfig adc_config = afe_config.adc();
            PGAConfig pga_config = afe_config.pga();
            LNAConfig lna_config = afe_config.lna();
            response_str += "ADC Configurations:\n";

            uint32_t ADC_RESOLUTION_RESET = daphne.getAfe()->setAFEFunction(afe_config.id(), "ADC_RESOLUTION_RESET", adc_config.resolution());
            response_str += "\tResolution : " + std::to_string(ADC_RESOLUTION_RESET) + "\n";

            uint32_t ADC_OUTPUT_FORMAT = daphne.getAfe()->setAFEFunction(afe_config.id(), "ADC_OUTPUT_FORMAT", adc_config.output_format());
            response_str += "\tOutput_format : " + std::to_string(ADC_OUTPUT_FORMAT) + "\n";

            uint32_t LSB_MSB_FIRST = daphne.getAfe()->setAFEFunction(afe_config.id(), "LSB_MSB_FIRST", adc_config.sb_first());
            response_str += "\tSB_first : " + std::to_string(LSB_MSB_FIRST) + "\n";

            response_str += "PGA Configurations:\n";
            uint32_t LPF_PROGRAMMABILITY = daphne.getAfe()->setAFEFunction(afe_config.id(), "LPF_PROGRAMMABILITY", pga_config.lpf_cut_frequency());
            response_str += "\tlpf_cut_frequency : " + std::to_string(LPF_PROGRAMMABILITY) + "\n";
            
            uint32_t PGA_INTEGRATOR_DISABLE = daphne.getAfe()->setAFEFunction(afe_config.id(), "PGA_INTEGRATOR_DISABLE", pga_config.integrator_disable());
            response_str += "\tintegrator_disable : " + std::to_string(PGA_INTEGRATOR_DISABLE) + "\n";
            
            uint32_t PGA_GAIN_CONTROL = daphne.getAfe()->setAFEFunction(afe_config.id(), "PGA_GAIN_CONTROL", pga_config.gain());
            response_str += "\tgain : " + std::to_string(PGA_GAIN_CONTROL) + "\n";
            
            response_str += "LNA Configurations:\n";
            uint32_t LNA_INPUT_CLAMP_SETTING = daphne.getAfe()->setAFEFunction(afe_config.id(), "LNA_INPUT_CLAMP_SETTING", lna_config.clamp());
            response_str += "\tclamp : " + std::to_string(LNA_INPUT_CLAMP_SETTING) + "\n";
            
            uint32_t LNA_GAIN = daphne.getAfe()->setAFEFunction(afe_config.id(), "LNA_GAIN", lna_config.gain());
            response_str += "\tgain : " + std::to_string(LNA_GAIN) + "\n";
            
            uint32_t LNA_INTEGRATOR_DISABLE = daphne.getAfe()->setAFEFunction(afe_config.id(), "LNA_INTEGRATOR_DISABLE", lna_config.integrator_disable());
            response_str += "\tintegrator_disable : " + std::to_string(LNA_INTEGRATOR_DISABLE) + "\n";
        }
    }catch(std::exception &e){
        std::cout << "Cought Exception: \n" << e.what();
        response_str = "Cought Exception: \n" + std::string(e.what());
        return false;
    }
    //std::cout << response_str << std::endl;
    return true;
}

bool writeAFERegister(const cmd_writeAFEReg &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value) {
    try {
        uint32_t afe = request.afeblock();
        afe = afe_definitions::AFE_board2PL_map.at(afe);
        uint32_t regAddr = request.regaddress();
        uint32_t regValue = request.regvalue();
        returned_value = daphne.getAfe()->setRegister(afe, regAddr, regValue);
        response_str = "AFE Register " + std::to_string(regAddr) 
                       + " written with value " + std::to_string(regValue) 
                       + " for AFE " + std::to_string(afe_definitions::AFE_PL2board_map.at(afe)) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
        daphne.setAfeRegDictValue(afe, regAddr, returned_value);
    } catch (std::exception &e) {
        response_str = "Error writting AFE Register: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEVgain(const cmd_writeAFEVGAIN &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value) {
    try {
        uint32_t afe = request.afeblock();
        afe = afe_definitions::AFE_board2PL_map.at(afe);
        uint32_t vgain = request.vgainvalue();
        if(vgain > 4095) throw std::invalid_argument("The VGAIN value " + std::to_string(vgain) + " is out of range. Expected range 0-4095");
        daphne.getDac()->setDacGain(afe, vgain);
        daphne.setAfeAttenuationDictValue(afe,vgain);
        returned_value = daphne.getAfeAttenuationDictValue(afe);
        response_str = "AFE VGAIN written successfully for AFE " + std::to_string(afe_definitions::AFE_PL2board_map.at(afe)) 
                       + ". VGAIN: " + std::to_string(vgain) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting AFE VGAIN: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEAttenuation(const cmd_writeAFEAttenuation &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value) {
    try {
        uint32_t afe = request.afeblock();
        afe = afe_definitions::AFE_board2PL_map.at(afe);
        uint32_t attenuation = request.attenuation();
        if(attenuation > 4095) throw std::invalid_argument("The attenuation value " + std::to_string(attenuation) + " is out of range. Range 0-4095");
        daphne.getDac()->setDacGain(afe, attenuation);
        daphne.setAfeAttenuationDictValue(afe,attenuation);
        returned_value = daphne.getAfeAttenuationDictValue(afe);
        response_str = "AFE Attenuation written successfully for AFE " 
                       + std::to_string(afe_definitions::AFE_PL2board_map.at(afe)) 
                       + ". Attenuation: " + std::to_string(attenuation) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting AFE Attenuation: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEBiasVoltage(const cmd_writeAFEBiasSet &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value){
    try {
        uint32_t afe = request.afeblock();
        afe = afe_definitions::AFE_board2PL_map.at(afe);
        uint32_t biasValue = request.biasvalue();
        if(biasValue > 4095) throw std::invalid_argument("The BIAS value " + std::to_string(biasValue) + " is out of range. Range 0-4095");
        daphne.getDac()->setDacBias(afe, biasValue);
        daphne.setBiasVoltageDictValue(afe, biasValue);
        returned_value = daphne.getBiasVoltageDictValue(afe);
        response_str = "AFE bias value written successfully for AFE " 
                       + std::to_string(afe_definitions::AFE_PL2board_map.at(afe)) 
                       + ". Bias value: " + std::to_string(biasValue) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting AFE Bias value: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeChannelTrim(const cmd_writeTrim_singleChannel &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value){
    try {
        uint32_t trimCh = request.trimchannel();
        uint32_t trimValue = request.trimvalue();
        uint32_t trimGain = request.trimgain();
        if(trimValue > 4095) throw std::invalid_argument("The Trim value " + std::to_string(trimValue) + " is out of range. Range 0-4095");
        if(trimCh > 39) throw std::invalid_argument("The Channel value " + std::to_string(trimCh) + " is out of range. Range 0-39");
        uint32_t afe = afe_definitions::AFE_board2PL_map.at(trimCh / 8);
        daphne.getDac()->setDacTrim(afe, trimCh % 8, trimValue, trimGain, false);
        daphne.setChTrimDictValue(trimCh, trimValue);
        returned_value = daphne.getChTrimDictValue(trimCh);
        response_str = "Trim value written successfully for Channel " + std::to_string(trimCh) + ". Trim value: " + std::to_string(trimValue) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting Channel Trim value: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeChannelOffset(const cmd_writeOFFSET_singleChannel &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value){
    try {
        uint32_t offsetCh = request.offsetchannel();
        uint32_t offsetValue = request.offsetvalue();
        uint32_t offsetGain = request.offsetgain();
        if(offsetValue > 4095) throw std::invalid_argument("The Offset value " + std::to_string(offsetValue) + " is out of range. Range 0-4095");
        if(offsetCh > 39) throw std::invalid_argument("The Channel value " + std::to_string(offsetCh) + " is out of range. Range 0-39");
        uint32_t afe = afe_definitions::AFE_board2PL_map.at(offsetCh / 8);
        daphne.getDac()->setDacOffset(afe, offsetCh % 8, offsetValue, offsetGain, false);
        daphne.setChOffsetDictValue(offsetCh, offsetValue);
        returned_value = daphne.getChOffsetDictValue(offsetCh);
        response_str = "Offset value written successfully for Channel " + std::to_string(offsetCh) + ". Offset value: " + std::to_string(offsetValue) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting Channel Offset value: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeBiasVoltageControl(const cmd_writeVbiasControl &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value){
    try {
        uint32_t controlValue = request.vbiascontrolvalue();
        bool biasEnable = request.enable();
        if(controlValue > 4095) throw std::invalid_argument("The Bias Control value " + std::to_string(controlValue) + " is out of range. Range 0-4095");
        uint32_t returnedControlValue = daphne.getDac()->setDacHvBias(controlValue, false, false);
        uint32_t returnedBiasEnable = daphne.getDac()->setBiasEnable(biasEnable);
        daphne.setBiasControlDictValue(controlValue);
        returned_value = returnedControlValue;
        response_str = "Bias Control value written successfully. Bias Control value: " + std::to_string(controlValue)
                       + " and Enable: " + std::to_string(returnedBiasEnable);
        response_str += " Returned value: " + std::to_string(returnedControlValue) + ".";
    } catch (std::exception &e) {
        response_str = "Error writting Bias Control value: " + std::string(e.what());
        return false;
    }
    return true;
}

bool dumpSpybuffer(const DumpSpyBuffersRequest &request, DumpSpyBuffersResponse &response, Daphne &daphne, std::string &response_str){
    try {
        uint32_t channel = request.channel();
        uint32_t numberOfSamples = request.numberofsamples();
        if(channel > 39) throw std::invalid_argument("The channel value " + std::to_string(channel) + " is out of range. Range 0-39");
        if(numberOfSamples > 4096 || numberOfSamples < 1) throw std::invalid_argument("The number of samples value " + std::to_string(numberOfSamples) + " is out of range. Range 1-4096");
        response.mutable_data()->Resize(numberOfSamples, 0); // This line allocates the required number of Data 
        for(int i=0; i<numberOfSamples; i++){
            response.set_data(i, daphne.getSpyBuffer()->getData(channel / 8, channel % 8, i));
        }
        response.set_channel(channel);
        response.set_numberofsamples(numberOfSamples);
        response_str = "Spybuffer channel " + std::to_string(channel) + " dumped correctly."
                       + " Number of samples: " + std::to_string(numberOfSamples);
    } catch (std::exception &e) {
        response_str = "Error dumping spybuffer: " + std::string(e.what());
        return false;
    }
    return true;
}

bool alignAFE(const cmd_alignAFE &request, cmd_alignAFE_response &response, Daphne &daphne, std::string &response_str){
    try {
        uint32_t afe = request.afe();
        if(afe > 4) throw std::invalid_argument("The AFE value " + std::to_string(afe) + " is out of range. Range 0-4");
        daphne.getFrontEnd()->doResetDelayCtrl();
        daphne.getFrontEnd()->doResetSerDesCtrl();
        daphne.getFrontEnd()->setEnableDelayVtc(0);
        daphne.setBestDelay(afe);
        daphne.setBestBitslip(afe);
        daphne.getFrontEnd()->setEnableDelayVtc(1);
        uint32_t delay = daphne.getFrontEnd()->getDelay(afe);
        uint32_t bitslip = daphne.getFrontEnd()->getBitslip(afe);
        response.set_delay(delay);
        response.set_bitslip(bitslip);
        response_str = "AFE number " + std::to_string(afe) + " aligned correctly.\n" +
                        "DELAY: " + std::to_string(delay) + "\n" + 
                        "BITSLIP: " + std::to_string(bitslip);
    } catch (std::exception &e) {
        response_str = "Error aligning AFE: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEFunction(const cmd_writeAFEFunction &request, cmd_writeAFEFunction_response &response, Daphne &daphne, std::string &response_str){
    try {
        uint32_t afeBlock = request.afeblock();
        std::string afeFunctionName = request.function();
        uint32_t confValue = request.configvalue();
        uint32_t returnedConfValue = daphne.getAfe()->setAFEFunction(afeBlock, afeFunctionName, confValue);
        response.set_function(afeFunctionName);
        response.set_configvalue(returnedConfValue);
        response.set_afeblock(afeBlock);
        response_str = "Function " + afeFunctionName + " in AFE " + std::to_string(afeBlock) + " configured correctly.\n"
                       + "Returned value: " + std::to_string(returnedConfValue);  
    } catch (std::exception &e) {
        response_str = "Error writting AFE function: " + std::string(e.what());
        return false;
    }
    return true;
}

bool setAFEReset(const cmd_setAFEReset &request, cmd_setAFEReset_response &response, Daphne &daphne, std::string &response_str){
    try{
        bool resetValue = request.resetvalue();
        uint32_t returnedResetValue = daphne.getAfe()->setReset((uint32_t)resetValue);
        response.set_resetvalue(returnedResetValue);
        response_str = "AFEs reset register with value " + std::to_string(resetValue) + ".\n"
                     + "Returned value: " + std::to_string(returnedResetValue);
    }catch(std::exception &e){
        response_str = "Error reseting AFEs: " + std::string(e.what());
        return false;
    }
    return true;
}

bool doAFEReset(const cmd_doAFEReset &request, cmd_doAFEReset_response &response, Daphne &daphne, std::string &response_str){
    try{
        uint32_t returnedResetValue = daphne.getAfe()->doReset();
        response_str = "AFEs doreset command successful.\n";
    }catch(std::exception &e){
        response_str = "Error reseting AFEs: " + std::string(e.what());
        return false;
    }
    return true;
}

bool setAFEPowerState(const cmd_setAFEPowerState &request, cmd_setAFEPowerState_response &response, Daphne &daphne, std::string &response_str){
    try{
        bool powerStateValue = request.powerstate();
        uint32_t returnedPowerStateValue = daphne.getAfe()->setPowerState((uint32_t)powerStateValue);
        response.set_powerstate(returnedPowerStateValue);
        response_str = "AFEs powerstate register with value " + std::to_string(powerStateValue) + ".\n"
                     + "Returned value: " + std::to_string(returnedPowerStateValue);
    }catch(std::exception &e){
        response_str = "Error setting AFEs power state: " + std::string(e.what());
        return false;
    }
    return true;
}

bool doSoftwareTrigger(const cmd_doSoftwareTrigger &request, cmd_doSoftwareTrigger_response &response, Daphne &daphne, std::string &response_str){
    try{
        daphne.getFrontEnd()->doTrigger();
        response_str = "Software doSoftwareTrigger command successful.\n";
    }catch(std::exception &e){
        response_str = "Error reseting AFEs: " + std::string(e.what());
        return false;
    }
    return true;
}

void process_request(const std::string& request_str, std::string& response_str, Daphne &daphne) {
    // Identify the message type
    // Here the not equal to std::npos is used to check if the string contains the substring
    // so the issue is to see if it really contains the substring. 
    // Apparently it does not!!!
    ControlEnvelope request_envelope, response_envelope;

    if(!request_envelope.ParseFromString(request_str)){
        response_str = "Request not recognized";
        return;
    }

    switch(request_envelope.type()){
        case CONFIGURE_CLKS: { // to be implemented
            ConfigureCLKsRequest clk_request;
            ConfigureCLKsResponse clk_response;
            //std::cout << "The request is a ConfigureCLKsRequest" << std::endl;
            if(clk_request.ParseFromString(request_envelope.payload())){
                clk_response.set_success(true);
                clk_response.set_message("CLKs configured successfully");
                response_envelope.set_type(CONFIGURE_CLKS);
                response_envelope.set_payload(clk_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                clk_response.set_success(false);
                clk_response.set_message("Payload not recognized");
                response_envelope.set_type(CONFIGURE_CLKS);
                response_envelope.set_payload(clk_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case CONFIGURE_FE: {
            ConfigureRequest cfg_request;
            ConfigureResponse cfg_response;
            //std::cout << "The request is a ConfigureRequest" << std::endl;
            if(cfg_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = configureDaphne(cfg_request, daphne, configure_message);
                cfg_response.set_success(is_success);
                cfg_response.set_message(configure_message);
                response_envelope.set_type(CONFIGURE_FE);
                response_envelope.set_payload(cfg_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                cfg_response.set_success(false);
                cfg_response.set_message("Payload not recognized");
                response_envelope.set_type(CONFIGURE_FE);
                response_envelope.set_payload(cfg_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_AFE_REG: {
            cmd_writeAFEReg write_afe_reg_request;
            cmd_writeAFEReg_response write_afe_reg_response;
            //std::cout << "The request is a WriteAfeRegRequest" << std::endl;
            if(write_afe_reg_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFERegister(write_afe_reg_request, daphne, configure_message, returned_value);
                write_afe_reg_response.set_success(is_success);
                write_afe_reg_response.set_message(configure_message);
                write_afe_reg_response.set_afeblock(write_afe_reg_request.afeblock());
                write_afe_reg_response.set_regaddress(write_afe_reg_request.regaddress());
                write_afe_reg_response.set_regvalue(returned_value);
                response_envelope.set_type(WRITE_AFE_REG);
                response_envelope.set_payload(write_afe_reg_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_afe_reg_response.set_success(false);
                write_afe_reg_response.set_message("WRITE_AFE_REG: Payload not recognized");
                response_envelope.set_type(WRITE_AFE_REG);
                response_envelope.set_payload(write_afe_reg_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_AFE_VGAIN: {
            cmd_writeAFEVGAIN write_afe_vgain_request;
            cmd_writeAFEVgain_response write_afe_vgain_response;
            //std::cout << "The request is a WriteAfeVgainRequest" << std::endl;
            if(write_afe_vgain_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFEVgain(write_afe_vgain_request, daphne, configure_message, returned_value);
                write_afe_vgain_response.set_success(is_success);
                write_afe_vgain_response.set_message(configure_message);
                write_afe_vgain_response.set_afeblock(write_afe_vgain_request.afeblock());
                write_afe_vgain_response.set_vgainvalue(returned_value);
                response_envelope.set_type(WRITE_AFE_VGAIN);
                response_envelope.set_payload(write_afe_vgain_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_afe_vgain_response.set_success(false);
                write_afe_vgain_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_AFE_VGAIN);
                response_envelope.set_payload(write_afe_vgain_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_AFE_BIAS_SET: {
            cmd_writeAFEBiasSet write_afe_biasset_request;
            cmd_writeAFEBiasSet_response write_afe_biasset_response;
            //std::cout << "The request is a WriteAfeBiasSetRequest" << std::endl;
            if(write_afe_biasset_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFEBiasVoltage(write_afe_biasset_request, daphne, configure_message, returned_value);
                write_afe_biasset_response.set_success(is_success);
                write_afe_biasset_response.set_message(configure_message);
                write_afe_biasset_response.set_afeblock(write_afe_biasset_request.afeblock());
                write_afe_biasset_response.set_biasvalue(returned_value);
                response_envelope.set_type(WRITE_AFE_BIAS_SET);
                response_envelope.set_payload(write_afe_biasset_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_afe_biasset_response.set_success(false);
                write_afe_biasset_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_AFE_BIAS_SET);
                response_envelope.set_payload(write_afe_biasset_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_TRIM_ALL_CH: { // to be implemented
            cmd_writeTRIM_allChannels write_trim_allchannels_request;
            cmd_writeTRIM_allChannels_response write_trim_allchannels_response;
            //std::cout << "The request is a WriteTrimAllChannelsRequest" << std::endl;
            if(write_trim_allchannels_request.ParseFromString(request_envelope.payload())){
                write_trim_allchannels_response.set_success(true);
                write_trim_allchannels_response.set_message("All channel trims written successfully");
                response_envelope.set_type(WRITE_TRIM_ALL_CH);
                response_envelope.set_payload(write_trim_allchannels_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_trim_allchannels_response.set_success(false);
                write_trim_allchannels_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_TRIM_ALL_CH);
                response_envelope.set_payload(write_trim_allchannels_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_TRIM_ALL_AFE: { // to be implemented
            cmd_writeTrim_allAFE write_trim_allafe_request;
            cmd_writeTrim_allAFE_response write_trim_allafe_response;
            //std::cout << "The request is a WriteTrimAllAfeRequest" << std::endl;
            if(write_trim_allafe_request.ParseFromString(request_envelope.payload())){
                write_trim_allafe_response.set_success(true);
                write_trim_allafe_response.set_message("All AFE trims written successfully");
                response_envelope.set_type(WRITE_TRIM_ALL_AFE);
                response_envelope.set_payload(write_trim_allafe_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_trim_allafe_response.set_success(false);
                write_trim_allafe_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_TRIM_ALL_AFE);
                response_envelope.set_payload(write_trim_allafe_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_TRIM_CH: { //Verified in DAPHNE V3
            cmd_writeTrim_singleChannel write_trim_singlechannel_request;
            cmd_writeTrim_singleChannel_response write_trim_singlechannel_response;
            //std::cout << "The request is a WriteTrimSingleChannelRequest" << std::endl;
            if(write_trim_singlechannel_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeChannelTrim(write_trim_singlechannel_request, daphne, configure_message, returned_value);
                write_trim_singlechannel_response.set_success(is_success);
                write_trim_singlechannel_response.set_message(configure_message);
                write_trim_singlechannel_response.set_trimchannel(write_trim_singlechannel_request.trimchannel());
                write_trim_singlechannel_response.set_trimvalue(returned_value);
                write_trim_singlechannel_response.set_trimgain(write_trim_singlechannel_request.trimgain());
                response_envelope.set_type(WRITE_TRIM_CH);
                response_envelope.set_payload(write_trim_singlechannel_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_trim_singlechannel_response.set_success(false);
                write_trim_singlechannel_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_TRIM_CH);
                response_envelope.set_payload(write_trim_singlechannel_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_OFFSET_ALL_CH: { // to be implemented
            cmd_writeOFFSET_allChannels write_offset_allchannels_request;
            cmd_writeOFFSET_allChannels_response write_offset_allchannels_response;
            //std::cout << "The request is a WriteOffsetAllChannelsRequest" << std::endl;
            if(write_offset_allchannels_request.ParseFromString(request_envelope.payload())){
                write_offset_allchannels_response.set_success(true);
                write_offset_allchannels_response.set_message("All channel offsets written successfully");
                response_envelope.set_type(WRITE_OFFSET_ALL_CH);
                response_envelope.set_payload(write_offset_allchannels_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_offset_allchannels_response.set_success(false);
                write_offset_allchannels_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_OFFSET_ALL_CH);
                response_envelope.set_payload(write_offset_allchannels_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_OFFSET_ALL_AFE: { // to be implemented
            cmd_writeOFFSET_allAFE write_offset_allafe_request;
            cmd_writeOFFSET_allAFE_response write_offset_allafe_response;
            //std::cout << "The request is a WriteOffsetAllAfeRequest" << std::endl;
            if(write_offset_allafe_request.ParseFromString(request_envelope.payload())){
                write_offset_allafe_response.set_success(true);
                write_offset_allafe_response.set_message("All AFE offsets written successfully");
                response_envelope.set_type(WRITE_OFFSET_ALL_AFE);
                response_envelope.set_payload(write_offset_allafe_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_offset_allafe_response.set_success(false);
                write_offset_allafe_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_OFFSET_ALL_AFE);
                response_envelope.set_payload(write_offset_allafe_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_OFFSET_CH: { //Verified in DAPHNE V3
            cmd_writeOFFSET_singleChannel write_offset_singlechannel_request;
            cmd_writeOFFSET_singleChannel_response write_offset_singlechannel_response;
            //std::cout << "The request is a WriteOffsetSingleChannelRequest" << std::endl;
            if(write_offset_singlechannel_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeChannelOffset(write_offset_singlechannel_request, daphne, configure_message, returned_value);
                write_offset_singlechannel_response.set_success(is_success);
                write_offset_singlechannel_response.set_message(configure_message);
                write_offset_singlechannel_response.set_offsetchannel(write_offset_singlechannel_request.offsetchannel());
                write_offset_singlechannel_response.set_offsetvalue(returned_value);
                write_offset_singlechannel_response.set_offsetgain(write_offset_singlechannel_request.offsetgain());
                write_offset_singlechannel_response.set_success(is_success);
                write_offset_singlechannel_response.set_message(configure_message);
                response_envelope.set_type(WRITE_OFFSET_CH);
                response_envelope.set_payload(write_offset_singlechannel_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_offset_singlechannel_response.set_success(false);
                write_offset_singlechannel_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_OFFSET_CH);
                response_envelope.set_payload(write_offset_singlechannel_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case WRITE_VBIAS_CONTROL: {
            cmd_writeVbiasControl write_vbias_control_request;
            cmd_writeVbiasControl_response write_vbias_control_response;
            //std::cout << "The request is a WriteVbiasControlRequest" << std::endl;
            if(write_vbias_control_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeBiasVoltageControl(write_vbias_control_request, daphne, configure_message, returned_value);
                write_vbias_control_response.set_vbiascontrolvalue(returned_value);
                write_vbias_control_response.set_success(is_success);
                write_vbias_control_response.set_message(configure_message);
                response_envelope.set_type(WRITE_VBIAS_CONTROL);
                response_envelope.set_payload(write_vbias_control_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_vbias_control_response.set_success(false);
                write_vbias_control_response.set_message("Payload not recognized");
                response_envelope.set_type(WRITE_VBIAS_CONTROL);
                response_envelope.set_payload(write_vbias_control_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_AFE_REG: { // to be implemented
            cmd_readAFEReg read_afe_reg_request;
            cmd_readAFEReg_response read_afe_reg_response;
            //std::cout << "The request is a ReadAfeRegRequest" << std::endl;
            if(read_afe_reg_request.ParseFromString(request_envelope.payload())){
                read_afe_reg_response.set_success(true);
                read_afe_reg_response.set_message("AFE register read successfully");
                response_envelope.set_type(READ_AFE_REG);
                response_envelope.set_payload(read_afe_reg_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_afe_reg_response.set_success(false);
                read_afe_reg_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_AFE_REG);
                response_envelope.set_payload(read_afe_reg_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_AFE_VGAIN: { // to be implemented
            cmd_readAFEVgain read_afe_vgain_request;
            cmd_readAFEVgain_response read_afe_vgain_response;
            //std::cout << "The request is a ReadAfeVgainRequest" << std::endl;
            if(read_afe_vgain_request.ParseFromString(request_envelope.payload())){
                read_afe_vgain_response.set_success(true);
                read_afe_vgain_response.set_message("AFE VGAIN read successfully");
                response_envelope.set_type(READ_AFE_VGAIN);
                response_envelope.set_payload(read_afe_vgain_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_afe_vgain_response.set_success(false);
                read_afe_vgain_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_AFE_VGAIN);
                response_envelope.set_payload(read_afe_vgain_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_AFE_BIAS_SET: { // to be implemented
            cmd_readAFEBiasSet read_afe_biasset_request;
            cmd_readAFEBiasSet_response read_afe_biasset_response;
            //std::cout << "The request is a ReadAfeBiasSetRequest" << std::endl;
            if(read_afe_biasset_request.ParseFromString(request_envelope.payload())){
                read_afe_biasset_response.set_success(true);
                read_afe_biasset_response.set_message("AFE Bias Set read successfully");
                response_envelope.set_type(READ_AFE_BIAS_SET);
                response_envelope.set_payload(read_afe_biasset_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_afe_biasset_response.set_success(false);
                read_afe_biasset_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_AFE_BIAS_SET);
                response_envelope.set_payload(read_afe_biasset_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_TRIM_ALL_CH: { // to be implemented
            cmd_readTrim_allChannels read_trim_allchannels_request;
            cmd_readTrim_allChannels_response read_trim_allchannels_response;
            //std::cout << "The request is a ReadTrimAllChannelsRequest" << std::endl;
            if(read_trim_allchannels_request.ParseFromString(request_envelope.payload())){
                read_trim_allchannels_response.set_success(true);
                read_trim_allchannels_response.set_message("All channel trims read successfully");
                response_envelope.set_type(READ_TRIM_ALL_CH);
                response_envelope.set_payload(read_trim_allchannels_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_trim_allchannels_response.set_success(false);
                read_trim_allchannels_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_TRIM_ALL_CH);
                response_envelope.set_payload(read_trim_allchannels_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_TRIM_ALL_AFE: { // to be implemented
            cmd_readTrim_allAFE read_trim_allafe_request;
            cmd_readTrim_allAFE_response read_trim_allafe_response;
            //std::cout << "The request is a ReadTrimAllAfeRequest" << std::endl;
            if(read_trim_allafe_request.ParseFromString(request_envelope.payload())){
                read_trim_allafe_response.set_success(true);
                read_trim_allafe_response.set_message("All AFE trims read successfully");
                response_envelope.set_type(READ_TRIM_ALL_AFE);
                response_envelope.set_payload(read_trim_allafe_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_trim_allafe_response.set_success(false);
                read_trim_allafe_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_TRIM_ALL_AFE);
                response_envelope.set_payload(read_trim_allafe_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_TRIM_CH: { // to be implemented
            cmd_readTrim_singleChannel read_trim_singlechannel_request;
            cmd_readTrim_singleChannel_response read_trim_singlechannel_response;
            //std::cout << "The request is a ReadTrimSingleChannelRequest" << std::endl;
            if(read_trim_singlechannel_request.ParseFromString(request_envelope.payload())){
                read_trim_singlechannel_response.set_success(true);
                read_trim_singlechannel_response.set_message("Single channel trim read successfully");
                response_envelope.set_type(READ_TRIM_CH);
                response_envelope.set_payload(read_trim_singlechannel_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_trim_singlechannel_response.set_success(false);
                read_trim_singlechannel_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_TRIM_CH);
                response_envelope.set_payload(read_trim_singlechannel_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_OFFSET_ALL_CH: { // to be implemented
            cmd_readOffset_allChannels read_offset_allchannels_request;
            cmd_readOffset_allChannels_response read_offset_allchannels_response;
            //std::cout << "The request is a ReadOffsetAllChannelsRequest" << std::endl;
            if(read_offset_allchannels_request.ParseFromString(request_envelope.payload())){
                read_offset_allchannels_response.set_success(true);
                read_offset_allchannels_response.set_message("All channel offsets read successfully");
                response_envelope.set_type(READ_OFFSET_ALL_CH);
                response_envelope.set_payload(read_offset_allchannels_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_offset_allchannels_response.set_success(false);
                read_offset_allchannels_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_OFFSET_ALL_CH);
                response_envelope.set_payload(read_offset_allchannels_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_OFFSET_ALL_AFE: { // to be implemented
            cmd_readOffset_allAFE read_offset_allafe_request;
            cmd_readOffset_allAFE_response read_offset_allafe_response;
            //std::cout << "The request is a ReadOffsetAllAfeRequest" << std::endl;
            if(read_offset_allafe_request.ParseFromString(request_envelope.payload())){
                read_offset_allafe_response.set_success(true);
                read_offset_allafe_response.set_message("All AFE offsets read successfully");
                response_envelope.set_type(READ_OFFSET_ALL_AFE);
                response_envelope.set_payload(read_offset_allafe_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_offset_allafe_response.set_success(false);
                read_offset_allafe_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_OFFSET_ALL_AFE);
                response_envelope.set_payload(read_offset_allafe_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_OFFSET_CH: { // to be implemented
            cmd_readOffset_singleChannel read_offset_singlechannel_request;
            cmd_readOffset_singleChannel_response read_offset_singlechannel_response;
            //std::cout << "The request is a ReadOffsetSingleChannelRequest" << std::endl;
            if(read_offset_singlechannel_request.ParseFromString(request_envelope.payload())){
                read_offset_singlechannel_response.set_success(true);
                read_offset_singlechannel_response.set_message("Single channel offset read successfully");
                response_envelope.set_type(READ_OFFSET_CH);
                response_envelope.set_payload(read_offset_singlechannel_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_offset_singlechannel_response.set_success(false);
                read_offset_singlechannel_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_OFFSET_CH);
                response_envelope.set_payload(read_offset_singlechannel_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_VBIAS_CONTROL: { // to be implemented
            cmd_readVbiasControl read_vbias_control_request;
            cmd_readVbiasControl_response read_vbias_control_response;
            //std::cout << "The request is a ReadVbiasControlRequest" << std::endl;
            if(read_vbias_control_request.ParseFromString(request_envelope.payload())){
                read_vbias_control_response.set_success(true);
                read_vbias_control_response.set_message("Vbias control read successfully");
                response_envelope.set_type(READ_VBIAS_CONTROL);
                response_envelope.set_payload(read_vbias_control_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_vbias_control_response.set_success(false);
                read_vbias_control_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_VBIAS_CONTROL);
                response_envelope.set_payload(read_vbias_control_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_CURRENT_MONITOR: { // to be implemented
            cmd_readCurrentMonitor read_current_monitor_request;
            cmd_readCurrentMonitor_response read_current_monitor_response;
            //std::cout << "The request is a ReadCurrentMonitorRequest" << std::endl;
            if(read_current_monitor_request.ParseFromString(request_envelope.payload())){
                read_current_monitor_response.set_success(true);
                read_current_monitor_response.set_message("Current monitor read successfully");
                response_envelope.set_type(READ_CURRENT_MONITOR);
                response_envelope.set_payload(read_current_monitor_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_current_monitor_response.set_success(false);
                read_current_monitor_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_CURRENT_MONITOR);
                response_envelope.set_payload(read_current_monitor_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case READ_BIAS_VOLTAGE_MONITOR: { // to be implemented
            cmd_readBiasVoltageMonitor read_bias_voltage_monitor_request;
            cmd_readBiasVoltageMonitor_response read_bias_voltage_monitor_response;
            //std::cout << "The request is a ReadBiasVoltageMonitorRequest" << std::endl;
            if(read_bias_voltage_monitor_request.ParseFromString(request_envelope.payload())){
                read_bias_voltage_monitor_response.set_success(true);
                read_bias_voltage_monitor_response.set_message("Bias voltage monitor read successfully");
                response_envelope.set_type(READ_BIAS_VOLTAGE_MONITOR);
                response_envelope.set_payload(read_bias_voltage_monitor_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                read_bias_voltage_monitor_response.set_success(false);
                read_bias_voltage_monitor_response.set_message("Payload not recognized");
                response_envelope.set_type(READ_BIAS_VOLTAGE_MONITOR);
                response_envelope.set_payload(read_bias_voltage_monitor_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case SET_AFE_RESET: {
            cmd_setAFEReset set_afe_reset_request;
            cmd_setAFEReset_response set_afe_reset_response;
            //std::cout << "The request is a SetAfeResetRequest" << std::endl;
            if(set_afe_reset_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = setAFEReset(set_afe_reset_request, set_afe_reset_response, daphne, configure_message);
                set_afe_reset_response.set_success(is_success);
                set_afe_reset_response.set_message(configure_message);
                response_envelope.set_type(SET_AFE_RESET);
                response_envelope.set_payload(set_afe_reset_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                set_afe_reset_response.set_success(false);
                set_afe_reset_response.set_message("Payload not recognized");
                response_envelope.set_type(SET_AFE_RESET);
                response_envelope.set_payload(set_afe_reset_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case DO_AFE_RESET: {
            cmd_doAFEReset do_afe_reset_request;
            cmd_doAFEReset_response do_afe_reset_response;
            //std::cout << "The request is a DoAfeResetRequest" << std::endl;
            if(do_afe_reset_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_succes = doAFEReset(do_afe_reset_request, do_afe_reset_response, daphne, configure_message);
                do_afe_reset_response.set_success(is_succes);
                do_afe_reset_response.set_message(configure_message);
                response_envelope.set_type(DO_AFE_RESET);
                response_envelope.set_payload(do_afe_reset_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                do_afe_reset_response.set_success(false);
                do_afe_reset_response.set_message("Payload not recognized");
                response_envelope.set_type(DO_AFE_RESET);
                response_envelope.set_payload(do_afe_reset_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }
        case SET_AFE_POWERSTATE: { // to be implemented
            cmd_setAFEPowerState set_afe_powerstate_request;
            cmd_setAFEPowerState_response set_afe_powerstate_response;
            //std::cout << "The request is a SetAfePowerStateRequest" << std::endl;
            if(set_afe_powerstate_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = setAFEPowerState(set_afe_powerstate_request, set_afe_powerstate_response, daphne, configure_message);
                set_afe_powerstate_response.set_success(is_success);
                set_afe_powerstate_response.set_message(configure_message);
                response_envelope.set_type(SET_AFE_POWERSTATE);
                response_envelope.set_payload(set_afe_powerstate_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                set_afe_powerstate_response.set_success(false);
                set_afe_powerstate_response.set_message("Payload not recognized");
                response_envelope.set_type(SET_AFE_POWERSTATE);
                response_envelope.set_payload(set_afe_powerstate_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }

        case DUMP_SPYBUFFER: {
            DumpSpyBuffersRequest dump_spybuffer_request;
            DumpSpyBuffersResponse dump_spybuffer_response;
            //std::cout << "The request is a DumpSpyBuffersRequest" << std::endl;
            if(dump_spybuffer_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = dumpSpybuffer(dump_spybuffer_request, dump_spybuffer_response, daphne, configure_message);
                dump_spybuffer_response.set_success(is_success);
                dump_spybuffer_response.set_message(configure_message);
                response_envelope.set_type(DUMP_SPYBUFFER);
                response_envelope.set_payload(dump_spybuffer_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                dump_spybuffer_response.set_success(false);
                dump_spybuffer_response.set_message("Payload not recognized");
                response_envelope.set_type(DUMP_SPYBUFFER);
                response_envelope.set_payload(dump_spybuffer_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }

        case ALIGN_AFE: {
            cmd_alignAFE alignAFE_request;
            cmd_alignAFE_response alignAFE_response;
            //std::cout << "The request is a cmd_alignAFE" << std::endl;
            if(alignAFE_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = alignAFE(alignAFE_request, alignAFE_response, daphne, configure_message);
                alignAFE_response.set_success(is_success);
                alignAFE_response.set_message(configure_message);
                response_envelope.set_type(ALIGN_AFE);
                response_envelope.set_payload(alignAFE_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                alignAFE_response.set_success(false);
                alignAFE_response.set_message("Payload not recognized");
                response_envelope.set_type(ALIGN_AFE);
                response_envelope.set_payload(alignAFE_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }

        case WRITE_AFE_FUNCTION: {
            cmd_writeAFEFunction write_AFE_function_request;
            cmd_writeAFEFunction_response write_AFE_function_response;
            //std::cout << "The request is a cmd_writeAFEFunction" << std::endl;
            if(write_AFE_function_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = writeAFEFunction(write_AFE_function_request, write_AFE_function_response, daphne, configure_message);
                write_AFE_function_response.set_success(is_success);
                write_AFE_function_response.set_message(configure_message);
                response_envelope.set_type(WRITE_AFE_FUNCTION);
                response_envelope.set_payload(write_AFE_function_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                write_AFE_function_response.set_success(false);
                write_AFE_function_response.set_message("Payload not recognized");
                response_envelope.set_type(ALIGN_AFE);
                response_envelope.set_payload(write_AFE_function_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }

        case DO_SOFTWARE_TRIGGER: {
            cmd_doSoftwareTrigger do_software_trigger_request;
            cmd_doSoftwareTrigger_response do_software_trigger_response;
            //std::cout << "The request is a DoSoftwareTriggerRequest" << std::endl;
            if(do_software_trigger_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = doSoftwareTrigger(do_software_trigger_request, do_software_trigger_response, daphne, configure_message);
                do_software_trigger_response.set_success(is_success);
                do_software_trigger_response.set_message(configure_message);
                response_envelope.set_type(DO_SOFTWARE_TRIGGER);
                response_envelope.set_payload(do_software_trigger_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                do_software_trigger_response.set_success(false);
                do_software_trigger_response.set_message("Payload not recognized");
                response_envelope.set_type(DO_SOFTWARE_TRIGGER);
                response_envelope.set_payload(do_software_trigger_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }
        }

        default: {
            response_str = "Request not recognized";
            return;
        }
    }
}

int main(int argc, char* argv[]) {

    std::map<std::string, std::string> args;
    std::string ip_address;
    int port;
    std::string config_file;

    // Parse arguments
    for (int i = 1; i < argc; i += 2) {
        if (i + 1 < argc) { // Ensure value exists
            args[argv[i]] = argv[i + 1];
        }
    }

    // Validate and extract -ip
    if (args.find("--ip") != args.end()) {
        ip_address = args["--ip"];
        std::cout << "IP Address: " << ip_address << std::endl;
    } else if(args.find("--config_file") == args.end()) {
        std::cerr << "Error: Missing -ip parameter.\n";
        std::cerr << "Usage: ./DaphneSlowController --ip <IP_ADDRESS> --port <PORT>\n";
        return 1;
    }

    // Validate and extract -port
    if (args.find("--port") != args.end()) {
        try {
            port = std::stoi(args["--port"]); // Convert string to int
            if (port < 1 || port > 65535) { // Here I must put a real range based.
                throw std::out_of_range("Port out of range");
            }
            std::cout << "Port: " << port << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "Error: Invalid port number. " << e.what() << std::endl;
            return 1;
        }
    } else if(args.find("--config_file") == args.end()){
        std::cerr << "Error: Missing --port parameter.\n";
        std::cerr << "Usage: ./DaphneSlowController --ip <IP_ADDRESS> --port <PORT>\n";
        return 1;
    }

    if (args.find("--config_file") != args.end()) {
        try {
            config_file = args["--config_file"]; // Convert string to int
            std::cout << "Configuration file: " << config_file << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "Error: Invalid  number. " << e.what() << std::endl;
            return 1;
        }
    } else if (args.find("--port") == args.end() && args.find("-ip") == args.end() && (args.find("--help") == args.end() || args.find("-h") == args.end())) {
        std::cerr << "Error: Missing parameters.\n";
        std::cerr << "Usage: ./DaphneSlowController --config_file <CONFIG_FILE> \n";
        return 1;
    }

    if (args.find("--help") != args.end() || args.find("-h") != args.end()) {
        std::cout << "Example: " << std::endl;
        std::cout << "\tsudo ./DaphneSlowController --ip <IP ADDRESS> --port <PORT NUMBER>" << std::endl;
        std::cout << "\tsudo ./DaphneSlowController --config-file <CONFIG FILE>" << std::endl;
        std::cout << "Arguments: " << std::endl;
        std::cout << "\t--ip :\t IP address of the DAPHNE device." << std::endl;
        std::cout << "\t--port :\t Port number." << std::endl;
        std::cout << "\t--config_file :\t Location of the .json file used for configuring the application." << std::endl;
        std::cout << "\t--help -h :\t Displays this help message." << std::endl;
    }

    zmq::context_t context(1);
    zmq::socket_t socket(context, ZMQ_REP);
    std::string socket_ip_address = "tcp://" + ip_address + ":" + std::to_string(port); 
    try {
        socket.bind(socket_ip_address.c_str());
        std::cout << "DAPHNE V3/Mezz Slow Controls V0_01_06" << std::endl;
        std::cout << "ZMQ Reply socket initialized in " << socket_ip_address << std::endl;
    } catch (std::exception &e){
        std::cerr << "Error initializing ZMQ socket: " << e.what() << std::endl;
        return 1;
    }

    Daphne daphne;
    while (true) {
        zmq::message_t request;
        auto recv_result = socket.recv(request, zmq::recv_flags::none);
        if(!recv_result){
            std::cerr << "socket.recv(request, zmq::recv_flags::none) failed!";
        }
        
        std::string request_str(static_cast<char*>(request.data()), request.size());
        std::string response_str;
        
        process_request(request_str, response_str, daphne);
        
        zmq::message_t response(response_str.size());
        memcpy(response.data(), response_str.data(), response_str.size());
        socket.send(response, zmq::send_flags::none);
    }
    return 0;
}