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

RuntimeState& GetRuntimeState() {
  static RuntimeState state;
  return state;
}

std::string ClassifyCommand(daphne::MessageTypeV2 type) {
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

bool IsAuditedCommand(daphne::MessageTypeV2 type) {
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

}  // namespace

void BeginCommand(const daphne::ControlEnvelopeV2& envelope, const std::string& requester) {
  if (!IsAuditedCommand(envelope.type())) return;
  CommandAudit audit;
  audit.valid = true;
  audit.message_id = envelope.msg_id();
  audit.name = daphne::MessageTypeV2_Name(envelope.type());
  audit.command_class = ClassifyCommand(envelope.type());
  audit.requester = requester;
  audit.route = envelope.route();
  audit.correlation_id = envelope.correl_id();
  audit.request_time_ns = envelope.timestamp_ns() != 0 ? envelope.timestamp_ns() : UnixTimeNs();
  audit.state = "Executing";
  RuntimeState& state = GetRuntimeState();
  std::lock_guard<std::mutex> lock(state.mutex);
  state.audit = std::move(audit);
}

void CompleteCommand(uint64_t message_id, bool handler_succeeded, const std::string& result) {
  RuntimeState& state = GetRuntimeState();
  std::lock_guard<std::mutex> lock(state.mutex);
  if (!state.audit.valid || state.audit.message_id != message_id) return;
  state.audit.completion_time_ns = UnixTimeNs();
  state.audit.state = handler_succeeded ? "Completed" : "Failed";
  state.audit.result = result;
}

void RecordActiveConfiguration(const daphne::ConfigureRequest& configuration) {
  RuntimeState& state = GetRuntimeState();
  std::lock_guard<std::mutex> lock(state.mutex);
  state.active_configuration = configuration;
}

namespace {

void CollectCommandAudit(SnapshotBuilder& builder, const CommandAudit& audit) {
  const std::string base = builder.NodeId("");
  if (audit.valid) {
    builder.SetString(base + "Operations.LastCommandId", std::to_string(audit.message_id));
    builder.SetString(base + "Operations.LastCommandName", audit.name);
    builder.SetString(base + "Operations.LastCommandClass", audit.command_class);
    builder.SetString(base + "Operations.LastCommandRequester", audit.requester,
                      TELEMETRY_QUALITY_INVALID,
                      "ZMQ routing identity is not an authenticated principal");
    builder.SetString(base + "Operations.LastCommandAuthority", "Unverified",
                      TELEMETRY_QUALITY_INVALID,
                      "ControlEnvelopeV2 has no authenticated authority field");
    builder.SetString(base + "Operations.LastCommandRoute", audit.route);
    builder.SetString(base + "Operations.LastCommandCorrelationId",
                      std::to_string(audit.correlation_id));
    builder.SetDateTime(base + "Operations.LastCommandRequestTime",
                        static_cast<int64_t>(audit.request_time_ns));
    if (audit.completion_time_ns != 0) {
      builder.SetDateTime(base + "Operations.LastCommandCompletionTime",
                          static_cast<int64_t>(audit.completion_time_ns));
    }
    builder.SetString(base + "Operations.LastCommandState", audit.state);
    builder.SetString(base + "Operations.LastCommandResult", audit.result);
    builder.SetBoolean(base + "Operations.LastCommandReadbackVerified", false,
                       TELEMETRY_QUALITY_INVALID,
                       "Generic transport completion is not hardware readback verification");
  }
}

void CollectActiveConfiguration(SnapshotBuilder& builder, const daphne::ConfigureRequest& config) {
  const std::string base = builder.NodeId("");
  builder.SetLong(base + "Configuration.Active.SelfTriggerThreshold",
                  static_cast<int64_t>(config.self_trigger_threshold()));
  builder.SetLong(base + "Configuration.Active.SelfTriggerXcorr",
                  static_cast<int64_t>(config.self_trigger_xcorr()));
  builder.SetLong(base + "Configuration.Active.TriggerPrimitiveConfig",
                  static_cast<int64_t>(config.tp_conf()));
  builder.SetLong(base + "Configuration.Active.CompensatorMask",
                  static_cast<int64_t>(config.compensator()));
  builder.SetLong(base + "Configuration.Active.InverterMask",
                  static_cast<int64_t>(config.inverters()));
  builder.SetInteger(base + "Configuration.Active.Slot", static_cast<int32_t>(config.slot()));
  builder.SetInteger(base + "Configuration.Active.RequestTimeoutMs",
                     static_cast<int32_t>(config.timeout_ms()));
  builder.SetInteger(base + "Configuration.Active.BiasControl",
                     static_cast<int32_t>(config.biasctrl()));
  builder.SetBoolean(base + "Firmware.ConfigurationReady", true);

  std::set<uint32_t> full_stream(config.full_stream_channels().begin(),
                                 config.full_stream_channels().end());
  std::ostringstream full_stream_list;
  bool first = true;
  for (const uint32_t channel : full_stream) {
    if (!first) full_stream_list << ',';
    first = false;
    full_stream_list << channel;
  }
  builder.SetString(base + "Configuration.Active.FullStreamChannelList", full_stream_list.str());
  for (uint32_t channel = 0; channel < 40; ++channel) {
    builder.SetBoolean(base + "Channels." + std::to_string(channel) + ".FullStreamEnabled",
                       full_stream.find(channel) != full_stream.end());
  }
  for (const auto& channel : config.channels()) {
    if (channel.id() >= 40) continue;
    const std::string channel_base = base + "Channels." + std::to_string(channel.id()) + ".";
    builder.SetInteger(channel_base + "Trim", static_cast<int32_t>(channel.trim()));
    builder.SetInteger(channel_base + "Offset", static_cast<int32_t>(channel.offset()));
    builder.SetInteger(channel_base + "Gain", static_cast<int32_t>(channel.gain()));
  }
  for (const auto& afe : config.afes()) {
    if (afe.id() >= 5) continue;
    const std::string afe_base = base + "AFE.Blocks." + std::to_string(afe.id()) + ".";
    builder.SetInteger(afe_base + "Attenuation", static_cast<int32_t>(afe.attenuators()));
    builder.SetInteger(afe_base + "VGain", static_cast<int32_t>(afe.attenuators()));
    builder.SetInteger(afe_base + "BiasSetCode", static_cast<int32_t>(afe.v_bias()));
    builder.SetBoolean(afe_base + "AdcResolution", afe.adc().resolution());
    builder.SetBoolean(afe_base + "AdcOutputFormat", afe.adc().output_format());
    builder.SetBoolean(afe_base + "AdcMsbFirst", afe.adc().sb_first());
    builder.SetInteger(afe_base + "PgaLpfCutFrequency",
                       static_cast<int32_t>(afe.pga().lpf_cut_frequency()));
    builder.SetBoolean(afe_base + "PgaIntegratorDisabled", afe.pga().integrator_disable());
    builder.SetBoolean(afe_base + "PgaGain", afe.pga().gain());
    builder.SetInteger(afe_base + "LnaClamp", static_cast<int32_t>(afe.lna().clamp()));
    builder.SetInteger(afe_base + "LnaGain", static_cast<int32_t>(afe.lna().gain()));
    builder.SetBoolean(afe_base + "LnaIntegratorDisabled", afe.lna().integrator_disable());
  }
}

}  // namespace

void CollectRuntimeTelemetry(SnapshotBuilder& builder) {
  std::optional<daphne::ConfigureRequest> configuration;
  CommandAudit audit;
  {
    RuntimeState& state = GetRuntimeState();
    std::lock_guard<std::mutex> lock(state.mutex);
    configuration = state.active_configuration;
    audit = state.audit;
  }

  CollectCommandAudit(builder, audit);
  if (configuration) {
    CollectActiveConfiguration(builder, *configuration);
  }
}

}  // namespace daphne_sc::telemetry
