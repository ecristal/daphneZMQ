#include <iostream>
#include <unordered_map>
#include <exception>
#include <zmq.hpp>
#include <optional>
#include "CLI/CLI.hpp"
#include <arpa/inet.h>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <atomic>
#include <vector>
#include <algorithm>

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

static void send_enveloped_over_router(zmq::socket_t &router, const zmq::message_t &client_id, const google::protobuf::Message &payload_msg, MessageType type) {
    // keep replies compatible with legacy clients.
    // ROUTER must send: [id][payload] (NO empty delimiter), so REQ receives a single frame.
    ControlEnvelope env;
    env.set_type(type);
    std::string payload;
    payload_msg.SerializeToString(&payload);
    env.set_payload(std::move(payload));


    std::string env_bytes;
    env.SerializeToString(&env_bytes);


    // multipart: [id][payload] — identity consumed by ROUTER; peer sees only [payload]
    router.send(zmq::buffer(client_id.data(), client_id.size()), zmq::send_flags::sndmore);
    router.send(zmq::buffer(env_bytes), zmq::send_flags::none);
}

static bool is_valid_ip(const std::string& s) {
    sockaddr_in  v4{};
    sockaddr_in6 v6{};
    return inet_pton(AF_INET, s.c_str(), &v4.sin_addr) == 1 ||
           inet_pton(AF_INET6, s.c_str(), &v6.sin6_addr) == 1;
}

// this tempalte class is a bounded queue that is used to 
// store waveforms in a thread-safe manner
// and pipeline them to send them in chuncks
template <class T>
class BoundedQueue {
private:
    std::mutex mutex_;
    std::condition_variable cv_not_empty_, cv_not_full_;
    size_t capacity;
    std::queue<T> queue_;
    bool closed_ = false;
public:
    explicit BoundedQueue(size_t capacity) : capacity(capacity){}

    void push(T item){
        std::unique_lock<std::mutex> lk(mutex_);
        cv_not_full_.wait(lk, [&]{
            return (queue_.size() < (capacity)) || closed_;
        });
        if (closed_) return;
        queue_.push(std::move(item));
        cv_not_empty_.notify_one();
    }

    bool pop(T& item){
        std::unique_lock<std::mutex> lk(mutex_);
        cv_not_empty_.wait(lk, [&]{
            return !queue_.empty() || closed_;
        });
        if (closed_ && queue_.empty()) return false;
        item = std::move(queue_.front());
        queue_.pop();
        cv_not_full_.notify_one();
        return true;
    }

    void close() {
        std::lock_guard<std::mutex> lk(mutex_);
        closed_ = true;
        cv_not_empty_.notify_all();
        cv_not_full_.notify_all();
    }
};

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
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        uint32_t regAddr = request.regaddress();
        uint32_t regValue = request.regvalue();
        returned_value = daphne.getAfe()->setRegister(afeBlock, regAddr, regValue);
        response_str = "AFE Register " + std::to_string(regAddr) 
                       + " written with value " + std::to_string(regValue) 
                       + " for AFE " + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) + ".";
        response_str += " Returned value: " + std::to_string(returned_value) + ".";
        daphne.setAfeRegDictValue(afeBlock, regAddr, returned_value);
    } catch (std::exception &e) {
        response_str = "Error writting AFE Register: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEVgain(const cmd_writeAFEVGAIN &request, Daphne &daphne, std::string &response_str, uint32_t &returned_value) {
    try {
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        uint32_t vgain = request.vgainvalue();
        if(vgain > 4095) throw std::invalid_argument("The VGAIN value " + std::to_string(vgain) + " is out of range. Expected range 0-4095");
        daphne.getDac()->setDacGain(afeBlock, vgain);
        daphne.setAfeAttenuationDictValue(afeBlock,vgain);
        returned_value = daphne.getAfeAttenuationDictValue(afeBlock);
        response_str = "AFE VGAIN written successfully for AFE " + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) 
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
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        uint32_t attenuation = request.attenuation();
        if(attenuation > 4095) throw std::invalid_argument("The attenuation value " + std::to_string(attenuation) + " is out of range. Range 0-4095");
        daphne.getDac()->setDacGain(afeBlock, attenuation);
        daphne.setAfeAttenuationDictValue(afeBlock,attenuation);
        returned_value = daphne.getAfeAttenuationDictValue(afeBlock);
        response_str = "AFE Attenuation written successfully for AFE " 
                       + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) 
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
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        uint32_t biasValue = request.biasvalue();
        if(biasValue > 4095) throw std::invalid_argument("The BIAS value " + std::to_string(biasValue) + " is out of range. Range 0-4095");
        daphne.getDac()->setDacBias(afeBlock, biasValue);
        daphne.setBiasVoltageDictValue(afeBlock, biasValue);
        returned_value = daphne.getBiasVoltageDictValue(afeBlock);
        response_str = "AFE bias value written successfully for AFE " 
                       + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) 
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
        uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(trimCh / 8);
        daphne.getDac()->setDacTrim(afeBlock, trimCh % 8, trimValue, trimGain, false);
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
        uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(offsetCh / 8);
        daphne.getDac()->setDacOffset(afeBlock, offsetCh % 8, offsetValue, offsetGain, false);
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
        
        uint32_t numberOfSamples = request.numberofsamples();
        uint32_t numberOfWaveforms = request.numberofwaveforms();
        auto channelList = request.channellist();

        for(int i=0; i<channelList.size(); ++i){
            if(channelList[i] > 39) throw std::invalid_argument("The channel value " + std::to_string(channelList[i]) + " is out of range. Range 0-39");
        }

        bool softwareTrigger = request.softwaretrigger();
        if(numberOfSamples > 2048 || numberOfSamples < 1) throw std::invalid_argument("The number of samples value " + std::to_string(numberOfSamples) + " is out of range. Range 1-4096");
        
        auto* spyBuffer = daphne.getSpyBuffer();
        auto* frontEnd = daphne.getFrontEnd();

        response.mutable_data()->Resize(numberOfSamples*numberOfWaveforms*channelList.size(), 0);
        google::protobuf::RepeatedField<uint32_t>* data_field = response.mutable_data();
        uint32_t* data_ptr = data_field->mutable_data();
        
        //daphne.getSpyBuffer()->setCurrentMappedChannelIndex(channel);
        // Let's calculate how much does it take to exxecute
        // the software trigger
        //std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
        if (channelList.size() == 1) {
        // No parallel, process channel sequentially
        uint32_t channel = channelList[0];
        uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(channel / 8);
        uint32_t afe_channel = channel % 8;
        channel = afeBlock * 8 + afe_channel; // Map to PL channel index
        for (int j = 0; j < numberOfWaveforms; ++j) {
            if (softwareTrigger) frontEnd->doTrigger();
            uint32_t* waveform_start = data_ptr + numberOfSamples * j;
            spyBuffer->extractMappedDataBulkSIMD(waveform_start, numberOfSamples, channel);
        }
        } else {
            // Parallelize across channels for each waveform
            // First, we need to map the channels to their PL indices
            std::vector<uint32_t> mappedChannels;
            for (const auto& channel : channelList) {
                uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(channel / 8);
                uint32_t afe_channel = channel % 8;
                mappedChannels.push_back(afeBlock * 8 + afe_channel); // Map to PL channel index
            }
            for (int j = 0; j < numberOfWaveforms; ++j) {
                if (softwareTrigger) frontEnd->doTrigger();
                //#pragma omp parallel for
                for (int i = 0; i < mappedChannels.size(); ++i) {
                    uint32_t channel = mappedChannels[i];
                    uint32_t* waveform_start = data_ptr + numberOfSamples * (j * mappedChannels.size() + i);
                    spyBuffer->extractMappedDataBulkSIMD(waveform_start, numberOfSamples, channel);
                }
            }
        }
        //std::chrono::steady_clock::time_point end = std::chrono::steady_clock::now();
        //std::chrono::duration<double> elapsed = end - start;
        //std::cout << "Time taken to dump spybuffer: " << elapsed.count() << " seconds." << std::endl;
        auto* resp_channel_list = response.mutable_channellist();
        resp_channel_list->Clear(); // ensure it's empty
        resp_channel_list->Reserve(channelList.size()); // reserve space for speed (optional)
        for(int i = 0; i < channelList.size(); ++i){
            resp_channel_list->Add(channelList[i]);
        }
        
        response.set_numberofsamples(numberOfSamples);
        response.set_numberofwaveforms(numberOfWaveforms);
        //response_str = "Spybuffer channel " + std::to_string(channel) + " dumped correctly."
        //               + " Number of samples: " + std::to_string(numberOfSamples);
        response_str = "OK";
    } catch (std::exception &e) {
        response_str = "Error dumping spybuffer: " + std::string(e.what());
        return false;
    }
    return true;
}

// this function handles the unique dumpSpybuffer in chunk mode,
// i.e. a pipelined approach to send waveforms in chunks to avoid
// memory issues when sending large number of waveforms
static void dumpSpyBufferChunk(const DumpSpyBuffersChunkRequest &request, Daphne &daphne, zmq::socket_t &router, const zmq::message_t &client_id){

    const auto &channelList = request.channellist();
    uint32_t numberOfSamples = request.numberofsamples();
    uint32_t numberOfWaveforms = request.numberofwaveforms();
    bool softwareTrigger = request.softwaretrigger();
    std::string requestId = request.requestid();
    uint32_t chunkSize = request.chunksize();

    if (channelList.empty()) {
        throw std::invalid_argument("Channel list is empty.");
    }
    if (numberOfSamples <= 0 || numberOfSamples > 2048) {
        throw std::invalid_argument("Number of samples must be greater than zero and no greater than 2048.");
    }
    if(numberOfWaveforms == 0) {
        throw std::invalid_argument("Number of waveforms must be greater than zero");
    }
    if(chunkSize == 0 || chunkSize > 1024) {
        throw std::invalid_argument("Chunk size must be greater than zero and no greater than 1024.");
    }
    for(int i=0; i<channelList.size(); ++i){
        if(channelList[i] > 39) throw std::invalid_argument("The channel value " + std::to_string(channelList[i]) + " is out of range. Range 0-39");
    }

    std::vector<uint32_t> mappedChannels;
    for (const auto& channel : channelList) {
        uint32_t afeBlock = afe_definitions::AFE_board2PL_map.at(channel / 8);
        uint32_t afe_channel = channel % 8;
        mappedChannels.push_back(afeBlock * 8 + afe_channel); // Map to PL channel index
    }
        
    struct ChunkPacket {
        uint32_t chunk_seq;
        uint32_t wf_start;
        uint32_t wf_count;
        std::vector<uint32_t> data;
    };
    BoundedQueue<ChunkPacket> queue(2);
    std::atomic<bool> had_error(false);
    
    auto* spyBuffer = daphne.getSpyBuffer();
    auto* frontEnd = daphne.getFrontEnd();

    std::thread producer([&]{
        try{
            uint32_t seq = 0;
            for (uint32_t wf_start = 0; wf_start < numberOfWaveforms; wf_start += chunkSize) {
                uint32_t wf_count = std::min(chunkSize, numberOfWaveforms - wf_start); // how many waveforms to process in this chunk. 
                                                                                       // If wf_start + chunkSize exceeds numberOfWaveforms, 
                                                                                       // it will take the remaining waveforms.
                ChunkPacket packet;
                packet.chunk_seq = seq++;
                packet.wf_start = wf_start;
                packet.wf_count = wf_count;
                packet.data.resize(wf_count * numberOfSamples * mappedChannels.size(), 0);
                //std::cout << "Processing chunk " << packet.chunk_seq 
                //          << " with waveform start " << packet.wf_start 
                //          << " and count " << packet.wf_count
                //          << ". Processed: " << packet.wf_start + packet.wf_count << std::endl;

                for (uint32_t i = 0; i < wf_count; ++i) {
                    if (softwareTrigger) frontEnd->doTrigger();
                    for (size_t j = 0; j < mappedChannels.size(); ++j) {
                        uint32_t channel = mappedChannels[j];
                        uint32_t* waveform_start = packet.data.data() + (i * mappedChannels.size() + j) * numberOfSamples;
                        spyBuffer->extractMappedDataBulkSIMD(waveform_start, numberOfSamples, channel);
                    }
                }
                queue.push(std::move(packet));
            }
        }catch(const std::exception &e) {
            had_error = true;
        }
        queue.close(); // Signal that no more packets will be produced
    });
    // Now, the consumer than pops the queue and sends the packets
    ChunkPacket pack;
    while (queue.pop(pack)) { // the while loop will continue until the queue is closed and empty
        DumpSpyBuffersChunkResponse resp;
        resp.set_success(!had_error);
        resp.set_requestid(requestId);
        resp.set_chunkseq(pack.chunk_seq);
        resp.set_isfinal((pack.wf_start + pack.wf_count) >= numberOfWaveforms);
        resp.set_waveformstart(pack.wf_start);
        resp.set_waveformcount(pack.wf_count);
        resp.set_requesttotalwaveforms(numberOfWaveforms);
        resp.set_numberofsamples(numberOfSamples);
        auto *out_chl = resp.mutable_channellist();
        out_chl->Clear();
        out_chl->Reserve(channelList.size());
        for (auto ch : channelList){
            out_chl->Add(ch);
        }
        auto *out_data = resp.mutable_data();
        out_data->Add(pack.data.data(), pack.data.data() + pack.data.size());

        send_enveloped_over_router(router, client_id, resp, DUMP_SPYBUFFER_CHUNK);
    }

    if (producer.joinable()) producer.join();
}

bool alignAFE(const cmd_alignAFEs &request, cmd_alignAFEs_response &response, Daphne &daphne, std::string &response_str){
    try {
        uint32_t afeNum = 5;
        std::vector<uint32_t> delay = {0, 0, 0, 0, 0};
        std::vector<uint32_t> bitslip = {0, 0, 0, 0, 0};
        std::string response_str_ = "";
        //if(afeBlock > 4) throw std::invalid_argument("The AFE value " + std::to_string(afeBlock) + " is out of range. Range 0-4");
        daphne.getFrontEnd()->resetDelayCtrlValues();
        daphne.getFrontEnd()->doResetDelayCtrl();
        daphne.getFrontEnd()->doResetSerDesCtrl();
        daphne.getFrontEnd()->setEnableDelayVtc(0);
        for(int afeBlock = 0; afeBlock < afeNum; afeBlock++){
            daphne.setBestDelay(afeBlock);
            daphne.setBestBitslip(afeBlock);
        }
        for(int afeBlock = 0; afeBlock < afeNum; afeBlock++){
            delay[afeBlock] = daphne.getFrontEnd()->getDelay(afeBlock);
            bitslip[afeBlock] = daphne.getFrontEnd()->getBitslip(afeBlock);
            response_str_ = response_str_ +
                            "AFE_" + std::to_string(afeBlock) + "\n" 
                            "DELAY: " + std::to_string(delay[afeBlock]) + "\n" + 
                            "BITSLIP: " + std::to_string(bitslip[afeBlock]) + "\n";
        }
        daphne.getFrontEnd()->setEnableDelayVtc(1);
        //response.set_delay(delay);
        //response.set_bitslip(bitslip);
        response_str = "AFEs alignAFE command executed correctly.\n" + response_str_;
    } catch (std::exception &e) {
        response_str = "Error aligning AFE: " + std::string(e.what());
        return false;
    }
    return true;
}

bool writeAFEFunction(const cmd_writeAFEFunction &request, cmd_writeAFEFunction_response &response, Daphne &daphne, std::string &response_str){
    try {
        uint32_t afeBlock = request.afeblock();
        afeBlock = afe_definitions::AFE_board2PL_map.at(afeBlock);
        if(afeBlock > 4) throw std::invalid_argument("The AFE value " + std::to_string(afeBlock) + " is out of range. Range 0-4");
        std::string afeFunctionName = request.function();
        uint32_t confValue = request.configvalue();
        uint32_t returnedConfValue = daphne.getAfe()->setAFEFunction(afeBlock, afeFunctionName, confValue);
        response.set_function(afeFunctionName);
        response.set_configvalue(returnedConfValue);
        response.set_afeblock(afeBlock);
        response_str = "Function " + afeFunctionName + " in AFE " + std::to_string(afe_definitions::AFE_PL2board_map.at(afeBlock)) + " configured correctly.\n"
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
            cmd_alignAFEs cmd_request;
            cmd_alignAFEs_response cmd_response;
            //std::cout << "The request is a cmd_alignAFEs" << std::endl;
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

static bool recv_multipart_compat(zmq::socket_t &sock, std::vector<zmq::message_t> &frames) {
    frames.clear();
    while (true) {
        zmq::message_t part;
        if (!sock.recv(part, zmq::recv_flags::none)) return false;
        frames.emplace_back(std::move(part));
        bool more = sock.get(zmq::sockopt::rcvmore);
        if (!more) break;
    }
    return true;
}

static void server_loop_router(zmq::context_t &ctx, const std::string &bind_endpoint, Daphne &daphne) {
    zmq::socket_t router(ctx, ZMQ_ROUTER);

    int sndhwm = 20000; 
    router.set(zmq::sockopt::sndhwm, sndhwm);
    int sndbuf = 4*1024*1024;  
    router.set(zmq::sockopt::sndbuf, sndbuf);
    int immediate = 1; 
    router.set(zmq::sockopt::immediate, immediate);
    router.bind(bind_endpoint);

    while (true) {
        
        std::vector<zmq::message_t> frames;
        if (!recv_multipart_compat(router, frames)) continue;
        if (frames.size() < 2) continue; 

        zmq::message_t &id = frames[0];
        
        zmq::message_t &payload = frames.back();

        ControlEnvelope req_env;
        if (!req_env.ParseFromArray(payload.data(), static_cast<int>(payload.size()))) {
            DumpSpyBuffersChunkResponse err; 
            err.set_success(false);
            err.set_message("Bad envelope");
            err.set_isfinal(true);
            send_enveloped_over_router(router, id, err, DUMP_SPYBUFFER_CHUNK);
            continue;
        }

        if (req_env.type() == DUMP_SPYBUFFER_CHUNK) {
            DumpSpyBuffersChunkRequest req;
            if (!req.ParseFromString(req_env.payload())) {
                DumpSpyBuffersChunkResponse err;
                err.set_success(false);
                err.set_message("Bad payload");
                err.set_isfinal(true);
                send_enveloped_over_router(router, id, err, DUMP_SPYBUFFER_CHUNK);
                continue;
            }
            dumpSpyBufferChunk(req, daphne, router, id);
            continue;
        }

        zmq::message_t one_reply;
        process_request(std::string(static_cast<char*>(payload.data()), payload.size()), one_reply, daphne);
        
        router.send(zmq::buffer(id.data(), id.size()), zmq::send_flags::sndmore);
        router.send(std::move(one_reply), zmq::send_flags::none);
        
    }
}

int main(int argc, char* argv[]) {

    CLI::App app{"Daphne Slow Controller"};

    std::optional<std::string> ip_address;
    std::optional<uint16_t> port;
    std::optional<std::string> config_file;

    app.add_option("-i,--ip", ip_address, "DAPHNE device IPv4 address.")
       ->check([](const std::string& s) {
            return is_valid_ip(s) ? std::string() : std::string("Invalid IP address");
       });
    app.add_option("--port", port, "Port number of the DAPHNE device.")
        ->check(CLI::Range(1, 65535));
    app.add_option("--config_file", config_file, "Path to the configuration file (not yet implemented).")
        ->check(CLI::ExistingFile);


    app.callback([&](){
        bool mode_config = config_file.has_value();
        bool mode_ipport = ip_address.has_value() || port.has_value();

        if (mode_config && mode_ipport) {
            throw CLI::ValidationError("Use either --config-file or (--ip AND --port), not both.");
        }
        if (!mode_config && !mode_ipport) {
            throw CLI::ValidationError("Missing parameters. Use --config-file or (--ip --port).");
        }
        if (mode_ipport && (!ip_address || !port)) {
            throw CLI::ValidationError("Both --ip and --port are required for IP mode.");
        }
    });

    try {
        app.parse(argc, argv);
        bool config_mode = config_file.has_value();
        bool ip_port_mode = ip_address.has_value() || port.has_value();

        if(config_mode && ip_port_mode) {
            throw CLI::ValidationError("Use either --config_file or (--ip AND --port), not both.");
        }else if(!config_mode && !ip_port_mode) {
            throw CLI::ValidationError("Missing parameters. Use --config_file or (--ip and --port).");
        }else if(ip_port_mode && (!ip_address || !port)) {
            throw CLI::ValidationError("Both --ip and --port are required for IP mode.");
        }
    } catch (const CLI::CallForHelp& e) {
        // --help was requested
        std::cout << app.help() << "\n";
        return 0;
    } catch (const CLI::ParseError &e) {
        return app.exit(e);
    }

    zmq::context_t context(1);
    std::string endpoint = "tcp://" + *ip_address + ":" + std::to_string(*port);


    try {
    std::cout << "DAPHNE V3/Mezz Slow Controls V0_01_31\n";
    std::cout << "ZMQ ROUTER server binding on " << endpoint << "\n";
    } catch (const std::exception &e) {
    std::cerr << "Initialization error: " << e.what() << "\n";
    return 1;
    }


    Daphne daphne;


    // Enters the ROUTER-based server loop. This function binds the ROUTER
    // and handles both legacy single-reply and new chunked streaming.
    server_loop_router(context, endpoint, daphne);
    return 0;
}
