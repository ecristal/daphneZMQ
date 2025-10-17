#pragma once
#include <cstdint>
#include <chrono>
#include <string>
#include "daphneV3_high_level_confs.pb.h"   // your high proto
#include "daphneV3_low_level_confs.pb.h"    // your low proto

namespace mezz {

inline uint64_t now_ns() {
  using namespace std::chrono;
  return duration_cast<nanoseconds>(steady_clock::now().time_since_epoch()).count();
}

inline daphne::MessageTypeV2 resp_type(daphne::MessageTypeV2 req) {
  int v = static_cast<int>(req);
  return static_cast<daphne::MessageTypeV2>((v & 1) ? v : (v + 1));
}

inline daphne::ControlEnvelopeV2 make_v2_resp(const daphne::ControlEnvelopeV2& req_env,
                                              daphne::MessageTypeV2 resp_type,
                                              const std::string& payload) {
  daphne::ControlEnvelopeV2 e;
  e.set_version(2);
  e.set_dir(daphne::DIR_RESPONSE);
  e.set_type(resp_type);
  e.set_task_id(req_env.task_id());
  e.set_correl_id(req_env.msg_id());
  e.set_msg_id(req_env.msg_id() + 1);
  e.set_timestamp_ns(now_ns());
  if (req_env.route().size()) e.set_route(req_env.route());
  e.set_payload(payload);
  return e;
}

} // namespace mezz
