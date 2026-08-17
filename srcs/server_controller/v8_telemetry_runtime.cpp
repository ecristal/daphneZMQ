#include "server_controller/v8_telemetry_runtime.hpp"

#include <algorithm>
#include <mutex>
#include <optional>
#include <set>
#include <sstream>
#include <string>

#include "server_controller/v8_telemetry.hpp"

namespace daphne_sc::telemetry {
namespace {

using daphne::telemetry::v8::TELEMETRY_QUALITY_INVALID;

struct CommandAudit {
  bool valid = false;
  uint64_t message_id = 0;
  std::string name;
  std::string command_class;
  std::string requester;
  std::string route;
  uint64_t correlation_id = 0;
  uint64_t request_time_ns = 0;
  uint64_t completion_time_ns = 0;
  std::string state;
  std::string result;
};

struct RuntimeState {
  std::mutex mutex;
  std::optional<daphne::ConfigureRequest> active_configuration;
  CommandAudit audit;
};

RuntimeState& runtime() {
  static RuntimeState state;
  return state;
}

std::string command_class(daphne::MessageTypeV2 type) {
  switch (type) {
    case daphne::MT2_CONFIGURE_CLKS_REQ:
    case daphne::MT2_CONFIGURE_FE_REQ:
    case daphne::MT2_CONFIGURE_HDMEZZ_BLOCK_REQ:
      return "Configure";
    case daphne::MT2_SET_AFE_RESET_REQ:
    case daphne::MT2_DO_AFE_RESET_REQ:
    case daphne::MT2_ALIGN_AFE_REQ:
      return "ResetOrAlignment";
    case daphne::MT2_DO_SOFTWARE_TRIGGER_REQ:
      return "DiagnosticAction";
    default:
      return "Write";
  }
}

}  // namespace

bool is_audited_command(daphne::MessageTypeV2 type) {
  switch (type) {
    case daphne::MT2_CONFIGURE_CLKS_REQ:
    case daphne::MT2_CONFIGURE_FE_REQ:
    case daphne::MT2_WRITE_AFE_REG_REQ:
    case daphne::MT2_WRITE_AFE_VGAIN_REQ:
    case daphne::MT2_WRITE_AFE_BIAS_SET_REQ:
    case daphne::MT2_WRITE_AFE_BIAS_CONTROLLED_SET_REQ:
    case daphne::MT2_WRITE_TRIM_ALL_CH_REQ:
    case daphne::MT2_WRITE_TRIM_ALL_AFE_REQ:
    case daphne::MT2_WRITE_TRIM_CH_REQ:
    case daphne::MT2_WRITE_OFFSET_ALL_CH_REQ:
    case daphne::MT2_WRITE_OFFSET_ALL_AFE_REQ:
    case daphne::MT2_WRITE_OFFSET_CH_REQ:
    case daphne::MT2_WRITE_VBIAS_CONTROL_REQ:
    case daphne::MT2_SET_AFE_RESET_REQ:
    case daphne::MT2_DO_AFE_RESET_REQ:
    case daphne::MT2_SET_AFE_POWERSTATE_REQ:
    case daphne::MT2_WRITE_AFE_ATTENUATION_REQ:
    case daphne::MT2_ALIGN_AFE_REQ:
    case daphne::MT2_WRITE_AFE_FUNCTION_REQ:
    case daphne::MT2_DO_SOFTWARE_TRIGGER_REQ:
    case daphne::MT2_SET_HDMEZZ_BLOCK_ENABLE_REQ:
    case daphne::MT2_CONFIGURE_HDMEZZ_BLOCK_REQ:
    case daphne::MT2_SET_HDMEZZ_POWER_STATES_REQ:
    case daphne::MT2_CLEAR_HDMEZZ_ALERT_FLAG_REQ:
      return true;
    default:
      return false;
  }
}

void begin_command(const daphne::ControlEnvelopeV2& envelope,
                   const std::string& requester) {
  if (!is_audited_command(envelope.type())) return;
  CommandAudit audit;
  audit.valid = true;
  audit.message_id = envelope.msg_id();
  audit.name = daphne::MessageTypeV2_Name(envelope.type());
  audit.command_class = command_class(envelope.type());
  audit.requester = requester;
  audit.route = envelope.route();
  audit.correlation_id = envelope.correl_id();
  audit.request_time_ns = envelope.timestamp_ns() != 0 ? envelope.timestamp_ns() : unix_time_ns();
  audit.state = "Executing";
  std::lock_guard<std::mutex> lock(runtime().mutex);
  runtime().audit = std::move(audit);
}

void complete_command(uint64_t message_id, bool handler_succeeded,
                      const std::string& result) {
  std::lock_guard<std::mutex> lock(runtime().mutex);
  if (!runtime().audit.valid || runtime().audit.message_id != message_id) return;
  runtime().audit.completion_time_ns = unix_time_ns();
  runtime().audit.state = handler_succeeded ? "Completed" : "Failed";
  runtime().audit.result = result;
}

void record_active_configuration(const daphne::ConfigureRequest& configuration) {
  std::lock_guard<std::mutex> lock(runtime().mutex);
  runtime().active_configuration = configuration;
}

void collect_runtime(SnapshotBuilder& builder) {
  std::optional<daphne::ConfigureRequest> configuration;
  CommandAudit audit;
  {
    std::lock_guard<std::mutex> lock(runtime().mutex);
    configuration = runtime().active_configuration;
    audit = runtime().audit;
  }
  const std::string base = "DAPHNE.Boards." + builder.board_id() + ".";
  if (audit.valid) {
    builder.set_string(base + "Operations.LastCommandId", std::to_string(audit.message_id));
    builder.set_string(base + "Operations.LastCommandName", audit.name);
    builder.set_string(base + "Operations.LastCommandClass", audit.command_class);
    builder.set_string(base + "Operations.LastCommandRequester", audit.requester,
                       TELEMETRY_QUALITY_INVALID,
                       "ZMQ routing identity is not an authenticated principal");
    builder.set_string(base + "Operations.LastCommandAuthority", "Unverified",
                       TELEMETRY_QUALITY_INVALID,
                       "ControlEnvelopeV2 has no authenticated authority field");
    builder.set_string(base + "Operations.LastCommandRoute", audit.route);
    builder.set_string(base + "Operations.LastCommandCorrelationId",
                       std::to_string(audit.correlation_id));
    builder.set_datetime(base + "Operations.LastCommandRequestTime",
                         static_cast<int64_t>(audit.request_time_ns));
    if (audit.completion_time_ns != 0) {
      builder.set_datetime(base + "Operations.LastCommandCompletionTime",
                           static_cast<int64_t>(audit.completion_time_ns));
    }
    builder.set_string(base + "Operations.LastCommandState", audit.state);
    builder.set_string(base + "Operations.LastCommandResult", audit.result);
    builder.set_boolean(base + "Operations.LastCommandReadbackVerified", false,
                        TELEMETRY_QUALITY_INVALID,
                        "Generic transport completion is not hardware readback verification");
  }

  if (!configuration) return;
  const auto& config = *configuration;
  builder.set_long(base + "Configuration.Active.SelfTriggerThreshold",
                   static_cast<int64_t>(config.self_trigger_threshold()));
  builder.set_long(base + "Configuration.Active.SelfTriggerXcorr",
                   static_cast<int64_t>(config.self_trigger_xcorr()));
  builder.set_long(base + "Configuration.Active.TriggerPrimitiveConfig",
                   static_cast<int64_t>(config.tp_conf()));
  builder.set_long(base + "Configuration.Active.CompensatorMask",
                   static_cast<int64_t>(config.compensator()));
  builder.set_long(base + "Configuration.Active.InverterMask",
                   static_cast<int64_t>(config.inverters()));
  builder.set_integer(base + "Configuration.Active.Slot", static_cast<int32_t>(config.slot()));
  builder.set_integer(base + "Configuration.Active.RequestTimeoutMs",
                      static_cast<int32_t>(config.timeout_ms()));
  builder.set_integer(base + "Configuration.Active.BiasControl",
                      static_cast<int32_t>(config.biasctrl()));
  builder.set_boolean(base + "Firmware.ConfigurationReady", true);

  std::set<uint32_t> full_stream(config.full_stream_channels().begin(),
                                 config.full_stream_channels().end());
  std::ostringstream full_stream_list;
  bool first = true;
  for (const uint32_t channel : full_stream) {
    if (!first) full_stream_list << ',';
    first = false;
    full_stream_list << channel;
  }
  builder.set_string(base + "Configuration.Active.FullStreamChannelList", full_stream_list.str());
  for (uint32_t channel = 0; channel < 40; ++channel) {
    builder.set_boolean(base + "Channels." + std::to_string(channel) + ".FullStreamEnabled",
                        full_stream.find(channel) != full_stream.end());
  }
  for (const auto& channel : config.channels()) {
    if (channel.id() >= 40) continue;
    const std::string channel_base = base + "Channels." + std::to_string(channel.id()) + ".";
    builder.set_integer(channel_base + "Trim", static_cast<int32_t>(channel.trim()));
    builder.set_integer(channel_base + "Offset", static_cast<int32_t>(channel.offset()));
    builder.set_integer(channel_base + "Gain", static_cast<int32_t>(channel.gain()));
  }
  for (const auto& afe : config.afes()) {
    if (afe.id() >= 5) continue;
    const std::string afe_base = base + "AFE.Blocks." + std::to_string(afe.id()) + ".";
    builder.set_integer(afe_base + "Attenuation", static_cast<int32_t>(afe.attenuators()));
    builder.set_integer(afe_base + "VGain", static_cast<int32_t>(afe.attenuators()));
    builder.set_integer(afe_base + "BiasSetCode", static_cast<int32_t>(afe.v_bias()));
    builder.set_boolean(afe_base + "AdcResolution", afe.adc().resolution());
    builder.set_boolean(afe_base + "AdcOutputFormat", afe.adc().output_format());
    builder.set_boolean(afe_base + "AdcMsbFirst", afe.adc().sb_first());
    builder.set_integer(afe_base + "PgaLpfCutFrequency",
                        static_cast<int32_t>(afe.pga().lpf_cut_frequency()));
    builder.set_boolean(afe_base + "PgaIntegratorDisabled", afe.pga().integrator_disable());
    builder.set_boolean(afe_base + "PgaGain", afe.pga().gain());
    builder.set_integer(afe_base + "LnaClamp", static_cast<int32_t>(afe.lna().clamp()));
    builder.set_integer(afe_base + "LnaGain", static_cast<int32_t>(afe.lna().gain()));
    builder.set_boolean(afe_base + "LnaIntegratorDisabled", afe.lna().integrator_disable());
  }
}

}  // namespace daphne_sc::telemetry
