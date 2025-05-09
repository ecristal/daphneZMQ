#include <iostream>
#include <unordered_map>
#include <exception>
#include <zmq.hpp>

#include "Daphne.hpp"
#include "protobuf/daphneV3_high_level_confs.pb.h"

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
        default: {
            response_str = "Request not recognized";
            return;
        }
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