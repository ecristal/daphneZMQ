#include "server_controller/spybuffer_chunker.hpp"

#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "Daphne.hpp"
#include "defines.hpp"
#include "daphneV3_high_level_confs.pb.h"
#include "server_controller/bounded_queue.hpp"

namespace daphne_sc {

namespace {
size_t max_chunk_bytes() {
  size_t max_bytes = 64ULL * 1024 * 1024;
  if (const char* v = std::getenv("DAPHNE_MAX_SPYBUFFER_CHUNK_BYTES")) {
    try {
      max_bytes = static_cast<size_t>(std::stoull(v));
    } catch (...) {
    }
  }
  return max_bytes;
}
}  // namespace

void for_each_spybuffer_chunk(
    const daphne::DumpSpyBuffersChunkRequest& request,
    Daphne& daphne,
    const std::function<void(const daphne::DumpSpyBuffersChunkResponse&)>& on_chunk) {
  const auto& channel_list = request.channellist();
  const uint32_t number_of_samples = request.numberofsamples();
  const uint32_t number_of_waveforms = request.numberofwaveforms();
  const bool software_trigger = request.softwaretrigger();
  const std::string request_id = request.requestid();
  const uint32_t chunk_size = request.chunksize();

  if (channel_list.empty()) throw std::invalid_argument("Empty channel list");
  if (number_of_samples == 0 || number_of_samples > 2048)
    throw std::invalid_argument("Invalid numberOfSamples");
  if (number_of_waveforms == 0) throw std::invalid_argument("Invalid numberOfWaveforms");
  if (chunk_size == 0 || chunk_size > 1024) throw std::invalid_argument("Invalid chunkSize");

  for (const auto ch : channel_list) {
    if (ch > 39) throw std::invalid_argument("Channel out of range (0..39)");
  }

  std::vector<uint32_t> mapped_channels;
  mapped_channels.reserve(static_cast<size_t>(channel_list.size()));
  for (const auto ch : channel_list) {
    const uint32_t afe_block = afe_definitions::AFE_board2PL_map.at(ch / 8);
    const uint32_t afe_chan = ch % 8;
    mapped_channels.push_back(afe_block * 8 + afe_chan);
  }

  struct ChunkPacket {
    uint32_t seq = 0;
    uint32_t wf_start = 0;
    uint32_t wf_count = 0;
    std::vector<uint32_t> data;
  };

  BoundedQueue<ChunkPacket> queue(2);
  std::atomic<bool> had_error(false);

  auto* spy_buffer = daphne.getSpyBuffer();
  auto* frontend = daphne.getFrontEnd();

  const size_t bytes_per_chunk =
      static_cast<size_t>(chunk_size) * number_of_samples * mapped_channels.size() * sizeof(uint32_t);
  if (bytes_per_chunk > max_chunk_bytes()) {
    throw std::invalid_argument("Requested chunk exceeds DAPHNE_MAX_SPYBUFFER_CHUNK_BYTES; lower chunkSize");
  }

  std::thread producer([&] {
    try {
      uint32_t seq = 0;
      for (uint32_t wf_start = 0; wf_start < number_of_waveforms; wf_start += chunk_size) {
        const uint32_t wf_count = std::min(chunk_size, number_of_waveforms - wf_start);
        ChunkPacket packet;
        packet.seq = seq++;
        packet.wf_start = wf_start;
        packet.wf_count = wf_count;
        packet.data.resize(static_cast<size_t>(wf_count) * number_of_samples *
                               mapped_channels.size(),
                           0);

        for (uint32_t i = 0; i < wf_count; ++i) {
          if (software_trigger) frontend->doTrigger();
          for (size_t j = 0; j < mapped_channels.size(); ++j) {
            const uint32_t chan = mapped_channels[j];
            uint32_t* dst = packet.data.data() +
                            (static_cast<size_t>(i) * mapped_channels.size() + j) *
                                number_of_samples;
            spy_buffer->extractMappedDataBulkSIMD(dst, number_of_samples, chan);
          }
        }

        queue.push(std::move(packet));
      }
    } catch (...) {
      had_error.store(true);
    }
    queue.close();
  });

  ChunkPacket packet;
  while (queue.pop(packet)) {
    daphne::DumpSpyBuffersChunkResponse resp;
    resp.set_success(!had_error.load());
    resp.set_requestid(request_id);
    resp.set_chunkseq(packet.seq);
    resp.set_isfinal((packet.wf_start + packet.wf_count) >= number_of_waveforms);
    resp.set_waveformstart(packet.wf_start);
    resp.set_waveformcount(packet.wf_count);
    resp.set_requesttotalwaveforms(number_of_waveforms);
    resp.set_numberofsamples(number_of_samples);

    auto* out_channels = resp.mutable_channellist();
    out_channels->Clear();
    out_channels->Reserve(channel_list.size());
    for (const auto ch : channel_list) out_channels->Add(ch);

    auto* out_data = resp.mutable_data();
    out_data->Add(packet.data.data(), packet.data.data() + packet.data.size());

    on_chunk(resp);
  }

  if (producer.joinable()) producer.join();
}

}  // namespace daphne_sc
