#include <iostream>
#include <unordered_map>
#include <exception>
#include <zmq.hpp>

#include "Daphne.hpp"
#include "defines.hpp"
#include "protobuf/daphneV3_high_level_confs.pb.h"
#include "protobuf/daphneV3_low_level_confs.pb.h"

template <typename payloadMsg> void fill_zmq_message(payloadMsg& payload_message, MessageType message_type, ControlEnvelope& response_envelope, zmq::message_t& zmq_response){
    std::string payload;
    payload.resize(payload_message.ByteSizeLong());
    payload_message.SerializeToArray(payload.data(), payload.size());
    response_envelope.set_type(message_type);
    response_envelope.set_payload(std::move(payload));

    size_t envelope_size = response_envelope.ByteSizeLong();
    zmq_response.rebuild(envelope_size);
    response_envelope.SerializeToArray(zmq_response.data(), envelope_size);

}

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
        if(numberOfSamples > 2048 || numberOfSamples < 1) throw std::invalid_argument("The number of samples value " + std::to_string(numberOfSamples) + " is out of range. Range 1-4096");
        
        response.mutable_data()->Resize(numberOfSamples, 0);
        google::protobuf::RepeatedField<uint32_t>* data_field = response.mutable_data();
        uint32_t* data_ptr = data_field->mutable_data();
        
        daphne.getSpyBuffer()->setCurrentMappedChannelIndex(channel);
        for(int i=0; i<numberOfSamples; ++i){
            data_ptr[i] = daphne.getSpyBuffer()->getMappedData(i);
        }
        response.set_channel(channel);
        response.set_numberofsamples(numberOfSamples);
        //response_str = "Spybuffer channel " + std::to_string(channel) + " dumped correctly."
        //               + " Number of samples: " + std::to_string(numberOfSamples);
        response_str = "OK";
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

void process_request(const std::string& request_str, zmq::message_t& zmq_response, Daphne &daphne) {
    // Identify the message type
    // Here the not equal to std::npos is used to check if the string contains the substring
    // so the issue is to see if it really contains the substring. 
    // Apparently it does not!!!
    ControlEnvelope request_envelope, response_envelope;

    if(!request_envelope.ParseFromString(request_str)){
        return;
    }

    switch(request_envelope.type()){
        case CONFIGURE_CLKS: { // to be implemented
            ConfigureCLKsRequest cmd_request;
            ConfigureCLKsResponse cmd_response;
            //std::cout << "The request is a ConfigureCLKsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("CLKs configured successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case CONFIGURE_FE: {
            ConfigureRequest cmd_request;
            ConfigureResponse cmd_response;
            //std::cout << "The request is a ConfigureRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = configureDaphne(cmd_request, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_AFE_REG: {
            cmd_writeAFEReg cmd_request;
            cmd_writeAFEReg_response cmd_response;
            //std::cout << "The request is a WriteAfeRegRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFERegister(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_afeblock(cmd_request.afeblock());
                cmd_response.set_regaddress(cmd_request.regaddress());
                cmd_response.set_regvalue(returned_value);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_AFE_VGAIN: {
            cmd_writeAFEVGAIN cmd_request;
            cmd_writeAFEVgain_response cmd_response;
            //std::cout << "The request is a WriteAfeVgainRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFEVgain(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_afeblock(cmd_request.afeblock());
                cmd_response.set_vgainvalue(returned_value);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_AFE_BIAS_SET: {
            cmd_writeAFEBiasSet cmd_request;
            cmd_writeAFEBiasSet_response cmd_response;
            //std::cout << "The request is a WriteAfeBiasSetRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeAFEBiasVoltage(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_afeblock(cmd_request.afeblock());
                cmd_response.set_biasvalue(returned_value);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_TRIM_ALL_CH: { // to be implemented
            cmd_writeTRIM_allChannels cmd_request;
            cmd_writeTRIM_allChannels_response cmd_response;
            //std::cout << "The request is a WriteTrimAllChannelsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All channel trims written successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_TRIM_ALL_AFE: { // to be implemented
            cmd_writeTrim_allAFE cmd_request;
            cmd_writeTrim_allAFE_response cmd_response;
            //std::cout << "The request is a WriteTrimAllAfeRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All AFE trims written successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_TRIM_CH: { //Verified in DAPHNE V3
            cmd_writeTrim_singleChannel cmd_request;
            cmd_writeTrim_singleChannel_response cmd_response;
            //std::cout << "The request is a WriteTrimSingleChannelRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeChannelTrim(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_trimchannel(cmd_request.trimchannel());
                cmd_response.set_trimvalue(returned_value);
                cmd_response.set_trimgain(cmd_request.trimgain());
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_OFFSET_ALL_CH: { // to be implemented
            cmd_writeOFFSET_allChannels cmd_request;
            cmd_writeOFFSET_allChannels_response cmd_response;
            //std::cout << "The request is a WriteOffsetAllChannelsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All channel offsets written successfully");
                return;
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
                return;
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_OFFSET_ALL_AFE: { // to be implemented
            cmd_writeOFFSET_allAFE cmd_request;
            cmd_writeOFFSET_allAFE_response cmd_response;
            //std::cout << "The request is a WriteOffsetAllAfeRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All AFE offsets written successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
        }
        case WRITE_OFFSET_CH: { //Verified in DAPHNE V3
            cmd_writeOFFSET_singleChannel cmd_request;
            cmd_writeOFFSET_singleChannel_response cmd_response;
            //std::cout << "The request is a WriteOffsetSingleChannelRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeChannelOffset(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
                cmd_response.set_offsetchannel(cmd_request.offsetchannel());
                cmd_response.set_offsetvalue(returned_value);
                cmd_response.set_offsetgain(cmd_request.offsetgain());
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case WRITE_VBIAS_CONTROL: {
            cmd_writeVbiasControl cmd_request;
            cmd_writeVbiasControl_response cmd_response;
            //std::cout << "The request is a WriteVbiasControlRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                uint32_t returned_value;
                bool is_success = writeBiasVoltageControl(cmd_request, daphne, configure_message, returned_value);
                cmd_response.set_vbiascontrolvalue(returned_value);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_AFE_REG: { // to be implemented
            cmd_readAFEReg cmd_request;
            cmd_readAFEReg_response cmd_response;
            //std::cout << "The request is a ReadAfeRegRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("AFE register read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_AFE_VGAIN: { // to be implemented
            cmd_readAFEVgain cmd_request;
            cmd_readAFEVgain_response cmd_response;
            //std::cout << "The request is a ReadAfeVgainRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("AFE VGAIN read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_AFE_BIAS_SET: { // to be implemented
            cmd_readAFEBiasSet cmd_request;
            cmd_readAFEBiasSet_response cmd_response;
            //std::cout << "The request is a ReadAfeBiasSetRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("AFE Bias Set read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_TRIM_ALL_CH: { // to be implemented
            cmd_readTrim_allChannels cmd_request;
            cmd_readTrim_allChannels_response cmd_response;
            //std::cout << "The request is a ReadTrimAllChannelsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All channel trims read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_TRIM_ALL_AFE: { // to be implemented
            cmd_readTrim_allAFE cmd_request;
            cmd_readTrim_allAFE_response cmd_response;
            //std::cout << "The request is a ReadTrimAllAfeRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All AFE trims read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_TRIM_CH: { // to be implemented
            cmd_readTrim_singleChannel cmd_request;
            cmd_readTrim_singleChannel_response cmd_response;
            //std::cout << "The request is a ReadTrimSingleChannelRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Single channel trim read successfully");
                return;
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_OFFSET_ALL_CH: { // to be implemented
            cmd_readOffset_allChannels cmd_request;
            cmd_readOffset_allChannels_response cmd_response;
            //std::cout << "The request is a ReadOffsetAllChannelsRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All channel offsets read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_OFFSET_ALL_AFE: { // to be implemented
            cmd_readOffset_allAFE cmd_request;
            cmd_readOffset_allAFE_response cmd_response;
            //std::cout << "The request is a ReadOffsetAllAfeRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("All AFE offsets read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_OFFSET_CH: { // to be implemented
            cmd_readOffset_singleChannel cmd_request;
            cmd_readOffset_singleChannel_response cmd_response;
            //std::cout << "The request is a ReadOffsetSingleChannelRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Single channel offset read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_VBIAS_CONTROL: { // to be implemented
            cmd_readVbiasControl cmd_request;
            cmd_readVbiasControl_response cmd_response;
            //std::cout << "The request is a ReadVbiasControlRequest" << std::endl;
            if(cmd_response.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Vbias control read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_CURRENT_MONITOR: { // to be implemented
            cmd_readCurrentMonitor cmd_request;
            cmd_readCurrentMonitor_response cmd_response;
            //std::cout << "The request is a ReadCurrentMonitorRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Current monitor read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case READ_BIAS_VOLTAGE_MONITOR: { // to be implemented
            cmd_readBiasVoltageMonitor cmd_request;
            cmd_readBiasVoltageMonitor_response cmd_response;
            //std::cout << "The request is a ReadBiasVoltageMonitorRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                cmd_response.set_success(true);
                cmd_response.set_message("Bias voltage monitor read successfully");
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case SET_AFE_RESET: {
            cmd_setAFEReset cmd_request;
            cmd_setAFEReset_response cmd_response;
            //std::cout << "The request is a SetAfeResetRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = setAFEReset(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case DO_AFE_RESET: {
            cmd_doAFEReset cmd_request;
            cmd_doAFEReset_response cmd_response;
            //std::cout << "The request is a DoAfeResetRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_succes = doAFEReset(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_succes);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }
        case SET_AFE_POWERSTATE: { // to be implemented
            cmd_setAFEPowerState cmd_request;
            cmd_setAFEPowerState_response cmd_response;
            //std::cout << "The request is a SetAfePowerStateRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = setAFEPowerState(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        case DUMP_SPYBUFFER: {
            DumpSpyBuffersRequest cmd_request;
            DumpSpyBuffersResponse cmd_response;
            //std::cout << "The request is a DumpSpyBuffersRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = dumpSpybuffer(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        case ALIGN_AFE: {
            cmd_alignAFE cmd_request;
            cmd_alignAFE_response cmd_response;
            //std::cout << "The request is a cmd_alignAFE" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = alignAFE(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        case WRITE_AFE_FUNCTION: {
            cmd_writeAFEFunction cmd_request;
            cmd_writeAFEFunction_response cmd_response;
            //std::cout << "The request is a cmd_writeAFEFunction" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = writeAFEFunction(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        case DO_SOFTWARE_TRIGGER: {
            cmd_doSoftwareTrigger cmd_request;
            cmd_doSoftwareTrigger_response cmd_response;
            //std::cout << "The request is a DoSoftwareTriggerRequest" << std::endl;
            if(cmd_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = doSoftwareTrigger(cmd_request, cmd_response, daphne, configure_message);
                cmd_response.set_success(is_success);
                cmd_response.set_message(configure_message);
            }else{
                cmd_response.set_success(false);
                cmd_response.set_message("Payload not recognized");
            }
            fill_zmq_message(cmd_response, request_envelope.type(), response_envelope, zmq_response);
            return;
        }

        default: {
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
        std::cout << "DAPHNE V3/Mezz Slow Controls V0_01_15" << std::endl;
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
        //std::string response_str;
        zmq::message_t zmq_response;
        
        process_request(request_str, zmq_response, daphne);
        
        socket.send(zmq_response, zmq::send_flags::none);
    }
    return 0;
}