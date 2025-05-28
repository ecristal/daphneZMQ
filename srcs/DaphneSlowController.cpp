#include <iostream>
#include <unordered_map>
#include <exception>
#include <zmq.hpp>

#include "Daphne.hpp"
#include "protobuf/daphneV3_high_level_confs.pb.h"
#include "protobuf/daphneV3_low_level_confs.pb.h"

bool configureDaphne(const ConfigureRequest &requested_cfg, Daphne &daphne, std::string &response_str, std::unordered_map<uint32_t, uint32_t> &ch_afe_map) {
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
            daphne.getDac()->setDacTrim(ch_afe_map[ch_config.id()], ch_config.id() % 8, ch_config.trim(), true, true);
            daphne.getDac()->setDacOffset(ch_afe_map[ch_config.id()], ch_config.id() % 8, ch_config.offset(), true, true);
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
        uint32_t regAddr = request.regaddress();
        uint32_t regValue = request.regvalue();
        returned_value = daphne.getAfe()->setRegister(afe, regAddr, regValue);
        response_str = "AFE Register " + std::to_string(regAddr) + " written with value " + std::to_string(regValue) + " for AFE " + std::to_string(afe) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
    } catch (std::exception &e) {
        response_str = "Error writing AFE Register: " + std::string(e.what());
        return false;
    }
    return true;
}

void process_request(const std::string& request_str, std::string& response_str, Daphne &daphne, std::unordered_map<uint32_t, uint32_t> &ch_afe_map) {
    // Identify the message type
    // Here the not equal to std::npos is used to check if the string contains the substring
    // so the issue is to see if it really contains the substring. 
    // Apparently it does not!!!
    ControlEnvelope request_envelope, response_envelope;
    ConfigureCLKsRequest clk_request;
    ConfigureCLKsResponse clk_response;
    ConfigureRequest cfg_request;
    ConfigureResponse cfg_response;
    // DAPHNE V2 Legacy commands
    cmd_writeAFEReg write_afe_reg_request;
    cmd_writeAFEReg_response write_afe_reg_response;
    cmd_writeAFEVGAIN write_afe_vgain_request;
    cmd_writeAFEVgain_response write_afe_vgain_response;
    cmd_writeAFEBiasSet write_afe_biasset_request;
    cmd_writeAFEBiasSet_response write_afe_biasset_response;
    cmd_writeTRIM_allChannels write_trim_allchannels_request;
    cmd_writeTRIM_allChannels_response write_trim_allchannels_response;
    cmd_writeTrim_allAFE write_trim_allafe_request;
    cmd_writeTrim_allAFE_response write_trim_allafe_response;
    cmd_writeTrim_singleChannel write_trim_singlechannel_request;
    cmd_writeTrim_singleChannel_response write_trim_singlechannel_response;
    cmd_writeOFFSET_allChannels write_offset_allchannels_request;
    cmd_writeOFFSET_allChannels_response write_offset_allchannels_response;
    cmd_writeOFFSET_allAFE write_offset_allafe_request;
    cmd_writeOFFSET_allAFE_response write_offset_allafe_response;
    cmd_writeOFFSET_singleChannel write_offset_singlechannel_request;
    cmd_writeOFFSET_singleChannel_response write_offset_singlechannel_response;
    cmd_writeVbiasControl write_vbias_control_request;
    cmd_writeVbiasControl_response write_vbias_control_response;
    cmd_readAFEReg read_afe_reg_request;
    cmd_readAFEReg_response read_afe_reg_response;
    cmd_readAFEVgain read_afe_vgain_request;
    cmd_readAFEVgain_response read_afe_vgain_response;
    cmd_readAFEBiasSet read_afe_biasset_request;
    cmd_readAFEBiasSet_response read_afe_biasset_response;
    cmd_readTrim_allChannels read_trim_allchannels_request;
    cmd_readTrim_allChannels_response read_trim_allchannels_response;
    cmd_readTrim_allAFE read_trim_allafe_request;
    cmd_readTrim_allAFE_response read_trim_allafe_response;
    cmd_readTrim_singleChannel read_trim_singlechannel_request;
    cmd_readTrim_singleChannel_response read_trim_singlechannel_response;
    cmd_readOffset_allChannels read_offset_allchannels_request;
    cmd_readOffset_allChannels_response read_offset_allchannels_response;
    cmd_readOffset_allAFE read_offset_allafe_request;
    cmd_readOffset_allAFE_response read_offset_allafe_response;
    cmd_readOffset_singleChannel read_offset_singlechannel_request;
    cmd_readOffset_singleChannel_response read_offset_singlechannel_response;
    cmd_readVbiasControl read_vbias_control_request;
    cmd_readVbiasControl_response read_vbias_control_response;
    cmd_readCurrentMonitor read_current_monitor_request;
    cmd_readCurrentMonitor_response read_current_monitor_response;
    cmd_readBiasVoltageMonitor read_bias_voltage_monitor_request;
    cmd_readBiasVoltageMonitor_response read_bias_voltage_monitor_response;
    cmd_setAFEReset set_afe_reset_request;
    cmd_setAFEReset_response set_afe_reset_response;
    cmd_setAFEPowerDown set_afe_powerdown_request;
    cmd_setAFEPowerDown_response set_afe_powerdown_response;
    if(!request_envelope.ParseFromString(request_str)){
        response_str = "Request not recognized";
        return;
    }

    switch(request_envelope.type()){
        case CONFIGURE_CLKS: {
            std::cout << "The request is a ConfigureCLKsRequest" << std::endl;
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
            std::cout << "The request is a ConfigureRequest" << std::endl;
            if(cfg_request.ParseFromString(request_envelope.payload())){
                std::string configure_message;
                bool is_success = configureDaphne(cfg_request, daphne, configure_message, ch_afe_map);
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
        case WRITE_AFE_REG: { // to be implemented
            std::cout << "The request is a WriteAfeRegRequest" << std::endl;
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
        case WRITE_AFE_VGAIN: { // to be implemented
            std::cout << "The request is a WriteAfeVgainRequest" << std::endl;
            if(write_afe_vgain_request.ParseFromString(request_envelope.payload())){
                write_afe_vgain_response.set_success(true);
                write_afe_vgain_response.set_message("AFE VGAIN written successfully");
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
        case WRITE_AFE_BIAS_SET: { // to be implemented
            std::cout << "The request is a WriteAfeBiasSetRequest" << std::endl;
            if(write_afe_biasset_request.ParseFromString(request_envelope.payload())){
                write_afe_biasset_response.set_success(true);
                write_afe_biasset_response.set_message("AFE Bias Set written successfully");
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
            std::cout << "The request is a WriteTrimAllChannelsRequest" << std::endl;
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
            std::cout << "The request is a WriteTrimAllAfeRequest" << std::endl;
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
        case WRITE_TRIM_CH: { // to be implemented
            std::cout << "The request is a WriteTrimSingleChannelRequest" << std::endl;
            if(write_trim_singlechannel_request.ParseFromString(request_envelope.payload())){
                write_trim_singlechannel_response.set_success(true);
                write_trim_singlechannel_response.set_message("Single channel trim written successfully");
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
            std::cout << "The request is a WriteOffsetAllChannelsRequest" << std::endl;
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
            std::cout << "The request is a WriteOffsetAllAfeRequest" << std::endl;
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
        case WRITE_OFFSET_CH: { // to be implemented
            std::cout << "The request is a WriteOffsetSingleChannelRequest" << std::endl;
            if(write_offset_singlechannel_request.ParseFromString(request_envelope.payload())){
                write_offset_singlechannel_response.set_success(true);
                write_offset_singlechannel_response.set_message("Single channel offset written successfully");
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
        case WRITE_VBIAS_CONTROL: { // to be implemented
            std::cout << "The request is a WriteVbiasControlRequest" << std::endl;
            if(write_vbias_control_request.ParseFromString(request_envelope.payload())){
                write_vbias_control_response.set_success(true);
                write_vbias_control_response.set_message("Vbias control written successfully");
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
            std::cout << "The request is a ReadAfeRegRequest" << std::endl;
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
            std::cout << "The request is a ReadAfeVgainRequest" << std::endl;
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
            std::cout << "The request is a ReadAfeBiasSetRequest" << std::endl;
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
            std::cout << "The request is a ReadTrimAllChannelsRequest" << std::endl;
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
            std::cout << "The request is a ReadTrimAllAfeRequest" << std::endl;
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
            std::cout << "The request is a ReadTrimSingleChannelRequest" << std::endl;
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
            std::cout << "The request is a ReadOffsetAllChannelsRequest" << std::endl;
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
            std::cout << "The request is a ReadOffsetAllAfeRequest" << std::endl;
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
            std::cout << "The request is a ReadOffsetSingleChannelRequest" << std::endl;
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
            std::cout << "The request is a ReadVbiasControlRequest" << std::endl;
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
            std::cout << "The request is a ReadCurrentMonitorRequest" << std::endl;
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
            std::cout << "The request is a ReadBiasVoltageMonitorRequest" << std::endl;
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
        case SET_AFE_RESET: { // to be implemented
            std::cout << "The request is a SetAfeResetRequest" << std::endl;
            if(set_afe_reset_request.ParseFromString(request_envelope.payload())){
                set_afe_reset_response.set_success(true);
                set_afe_reset_response.set_message("AFE reset set successfully");
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
        case SET_AFE_POWERDOWN: { // to be implemented
            std::cout << "The request is a SetAfePowerDownRequest" << std::endl;
            if(set_afe_powerdown_request.ParseFromString(request_envelope.payload())){
                set_afe_powerdown_response.set_success(true);
                set_afe_powerdown_response.set_message("AFE power down set successfully");
                response_envelope.set_type(SET_AFE_POWERDOWN);
                response_envelope.set_payload(set_afe_powerdown_response.SerializeAsString());
                response_envelope.SerializeToString(&response_str);
                return;
            }else{
                set_afe_powerdown_response.set_success(false);
                set_afe_powerdown_response.set_message("Payload not recognized");
                response_envelope.set_type(SET_AFE_POWERDOWN);
                response_envelope.set_payload(set_afe_powerdown_response.SerializeAsString());
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

int main() {
    zmq::context_t context(1);
    zmq::socket_t socket(context, ZMQ_REP);
    socket.bind("tcp://193.206.157.36:9000");
    Daphne daphne;

    std::unordered_map<uint32_t, uint32_t> ch_afe_map = {
        {0, 0},
        {1, 0},
        {2, 0},
        {3, 0},
        {4, 0},
        {5, 0},
        {6, 0},
        {7, 0},
        {8, 1},
        {9, 1},
        {10, 1},
        {11, 1},
        {12, 1},
        {13, 1},
        {14, 1},
        {15, 1},
        {16, 2},
        {17, 2},
        {18, 2},
        {19, 2},
        {20, 2},
        {21, 2},
        {22, 2},
        {23, 2},
        {24, 3},
        {25, 3},
        {26, 3},
        {27, 3},
        {28, 3},
        {29, 3},
        {30, 3},
        {31, 3},
        {32, 4},
        {33, 4},
        {34, 4},
        {35, 4},
        {36, 4},
        {37, 4},
        {38, 4},
        {39, 4},
    };
    
    while (true) {
        zmq::message_t request;
        socket.recv(request, zmq::recv_flags::none);
        
        std::string request_str(static_cast<char*>(request.data()), request.size());
        std::string response_str;
        
        process_request(request_str, response_str, daphne, ch_afe_map);
        
        zmq::message_t response(response_str.size());
        memcpy(response.data(), response_str.data(), response_str.size());
        socket.send(response, zmq::send_flags::none);
    }
    return 0;
}