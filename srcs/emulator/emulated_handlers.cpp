#include "emulator/emulated_handlers.hpp"

#include <string>

#include "server_controller/slow_control_backend.hpp"

namespace daphne_sc {
namespace {

template <typename Message>
std::string serialize(const Message& message) {
  std::string output;
  message.SerializeToString(&output);
  return output;
}

}  // namespace

std::unordered_map<daphne::MessageTypeV2, V2Handler> make_emulated_v2_handlers(
    SlowControlBackend& backend) {
  std::unordered_map<daphne::MessageTypeV2, V2Handler> handlers;

  handlers[daphne::MT2_CONFIGURE_FE_REQ] = [&backend](const std::string& input,
                                                       std::string& output) {
    daphne::ConfigureRequest request;
    if (!request.ParseFromString(input)) {
      daphne::ConfigureResponse response;
      response.set_success(false);
      response.set_message("Bad ConfigureRequest payload");
      output = serialize(response);
      return;
    }
    output = serialize(backend.configure(request));
  };

  handlers[daphne::MT2_READ_TRIGGER_COUNTERS_REQ] = [&backend](const std::string& input,
                                                                std::string& output) {
    daphne::ReadTriggerCountersRequest request;
    if (!request.ParseFromString(input)) {
      daphne::ReadTriggerCountersResponse response;
      response.set_success(false);
      response.set_message("Bad ReadTriggerCountersRequest payload");
      output = serialize(response);
      return;
    }
    output = serialize(backend.read_trigger_counters(request));
  };

  handlers[daphne::MT2_READ_TEST_REG_REQ] = [&backend](const std::string& input,
                                                       std::string& output) {
    daphne::TestRegRequest request;
    if (!request.ParseFromString(input)) {
      daphne::TestRegResponse response;
      response.set_message("Bad TestRegRequest payload");
      output = serialize(response);
      return;
    }
    output = serialize(backend.read_test_register());
  };

  handlers[daphne::MT2_READ_GENERAL_INFO_REQ] = [&backend](const std::string& input,
                                                           std::string& output) {
    daphne::InfoRequest request;
    if (!request.ParseFromString(input)) {
      output = serialize(daphne::GeneralInfo{});
      return;
    }
    output = serialize(backend.read_general_info(request));
  };

  handlers[daphne::MT2_READ_TELEMETRY_SNAPSHOT_REQ] =
      [&backend](const std::string& input, std::string& output) {
        daphne::telemetry::v8::ReadTelemetrySnapshotRequest request;
        if (!request.ParseFromString(input)) {
          daphne::telemetry::v8::ReadTelemetrySnapshotResponse response;
          response.set_success(false);
          response.set_message("Bad ReadTelemetrySnapshotRequest payload");
          output = serialize(response);
          return;
        }
        output = serialize(backend.read_telemetry_snapshot(request));
      };

  return handlers;
}

}  // namespace daphne_sc
