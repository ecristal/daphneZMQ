#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <string>

#include "daphneV3_high_level_confs.pb.h"

namespace daphne_sc::v2 {

inline uint64_t now_ns() {
  using namespace std::chrono;
  return duration_cast<nanoseconds>(steady_clock::now().time_since_epoch()).count();
}

inline uint64_t next_msg_id() {
  static std::atomic<uint64_t> seq{1};
  const uint64_t n = now_ns();
  const uint64_t s = seq.fetch_add(1, std::memory_order_relaxed);
  return ((n << 16) ^ s) & ((1ULL << 63) - 1);
}

inline daphne::MessageTypeV2 response_type(daphne::MessageTypeV2 req) {
  const int v = static_cast<int>(req);
  if (v == 0) return daphne::MT2_UNSPECIFIED;
  return static_cast<daphne::MessageTypeV2>((v & 1) ? v : (v + 1));
}

inline daphne::ControlEnvelopeV2 make_response(const daphne::ControlEnvelopeV2& req,
                                               daphne::MessageTypeV2 resp_type,
                                               std::string payload) {
  daphne::ControlEnvelopeV2 out;
  out.set_version(2);
  out.set_dir(daphne::DIR_RESPONSE);
  out.set_type(resp_type);
  out.set_task_id(req.task_id());
  out.set_correl_id(req.msg_id());
  out.set_msg_id(next_msg_id());
  if (!req.route().empty()) out.set_route(req.route());
  out.set_timestamp_ns(now_ns());
  out.set_payload(std::move(payload));
  return out;
}

}  // namespace daphne_sc::v2

