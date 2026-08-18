#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "emulator/EmulatedDaphneBackend.hpp"
#include "emulator/emulated_handlers.hpp"
#include "server_controller/v8_telemetry.hpp"

namespace {

void Require(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAILED: " << message << '\n';
    std::exit(1);
  }
}

daphne::ConfigureRequest MakeRequest() {
  daphne::ConfigureRequest request;
  request.set_biasctrl(1300);
  request.set_self_trigger_threshold(17);

  for (const uint32_t channel_id : {0u, 39u}) {
    auto* channel = request.add_channels();
    channel->set_id(channel_id);
    channel->set_trim(channel_id + 10);
    channel->set_offset(channel_id + 20);
    channel->set_gain(1);
  }
  for (const uint32_t afe_id : {0u, 4u}) {
    auto* afe = request.add_afes();
    afe->set_id(afe_id);
    afe->set_attenuators(1600 + afe_id);
    afe->set_v_bias(100 + afe_id);
  }
  return request;
}

size_t ValidateExplicitSamples(const daphne::telemetry::v8::BoardTelemetry& telemetry) {
  using google::protobuf::FieldDescriptor;
  using google::protobuf::Message;

  size_t sample_count = 0;
  const auto* descriptor = telemetry.GetDescriptor();
  const auto* reflection = telemetry.GetReflection();
  Require(descriptor->field_count() == 316, "wire contract declares all 316 variable patterns");
  for (int field_index = 0; field_index < descriptor->field_count(); ++field_index) {
    const FieldDescriptor* field = descriptor->field(field_index);
    Require(field->options().HasExtension(daphne::telemetry::v8::opcua_node_pattern),
            "every wire field declares its OPC-UA mapping");
    const int entry_count = field->is_repeated() ? reflection->FieldSize(telemetry, field) : 1;
    Require(entry_count > 0, "every explicit wire field has at least one instance");
    for (int entry_index = 0; entry_index < entry_count; ++entry_index) {
      const Message* sample = nullptr;
      if (field->is_repeated()) {
        const Message& entry = reflection->GetRepeatedMessage(telemetry, field, entry_index);
        const FieldDescriptor* sample_field = entry.GetDescriptor()->FindFieldByName("sample");
        Require(sample_field != nullptr, "indexed wire entry carries a typed sample");
        sample = &entry.GetReflection()->GetMessage(entry, sample_field);
      } else {
        Require(reflection->HasField(telemetry, field), "scalar wire field is present");
        sample = &reflection->GetMessage(telemetry, field);
      }

      const auto* metadata_field = sample->GetDescriptor()->FindFieldByName("metadata");
      const auto* value_field = sample->GetDescriptor()->FindFieldByName("value");
      Require(metadata_field != nullptr && value_field != nullptr,
              "typed sample declares metadata and value");
      const auto& metadata_message = sample->GetReflection()->GetMessage(*sample, metadata_field);
      const auto* metadata =
          dynamic_cast<const daphne::telemetry::v8::SampleMetadata*>(&metadata_message);
      Require(metadata != nullptr, "typed sample uses SampleMetadata");
      Require(metadata->quality() != daphne::telemetry::v8::TELEMETRY_QUALITY_UNSPECIFIED,
              "every explicit sample has quality");
      Require(metadata->sample_time_unix_ns() != 0 && metadata->sample_monotonic_ns() != 0,
              "every explicit sample has source timestamps");
      if (metadata->quality() == daphne::telemetry::v8::TELEMETRY_QUALITY_UNAVAILABLE ||
          metadata->quality() == daphne::telemetry::v8::TELEMETRY_QUALITY_NOT_APPLICABLE) {
        Require(!sample->GetReflection()->HasField(*sample, value_field),
                "unavailable explicit sample does not fabricate a value");
      }
      ++sample_count;
    }
  }
  return sample_count;
}

}  // namespace

int main() {
  using namespace std::chrono_literals;
  using daphne_sc::emulator::BoardPhase;
  using daphne_sc::emulator::EmulatedDaphneBackend;
  using daphne_sc::emulator::TimingProfile;

  std::vector<std::chrono::nanoseconds> sleeps;
  TimingProfile timing;
  timing.startup_delay = 3ms;
  timing.afe_reset = 100us;
  timing.afe_power_settle = 5ms;
  timing.channel_dac_write = 7us;
  timing.afe_program = 11us;
  timing.delayctrl_reset = 10ms;
  timing.serdes_reset = 10ms;
  timing.spy_snapshot = 1ms;
  timing.delay_taps = 2;
  timing.bitslip_taps = 1;
  timing.verification_reads = 1;

  EmulatedDaphneBackend backend(
      timing, [&](std::chrono::nanoseconds duration) { sleeps.push_back(duration); });
  Require(backend.snapshot().phase == BoardPhase::kPoweredOff, "board starts powered off");
  backend.boot();
  Require(backend.snapshot().phase == BoardPhase::kReady, "boot reaches ready");
  Require(sleeps.size() == 1 && sleeps.front() == 3ms, "boot delay is scheduled");

  const auto request = MakeRequest();
  const auto expected_duration = backend.nominal_configure_duration(request);
  const auto response = backend.configure(request);
  Require(response.success(), "valid configuration succeeds");
  Require(response.message().find("generation=1") != std::string::npos,
          "response includes configuration generation");

  const auto snapshot = backend.snapshot();
  Require(snapshot.phase == BoardPhase::kReady, "configuration returns board to ready");
  Require(snapshot.configuration_generation == 1, "generation increments");
  Require(snapshot.channels[0].configured && snapshot.channels[39].configured,
          "requested channels are configured");
  Require(snapshot.channels[0].threshold == 17, "threshold is retained");
  Require(snapshot.afes[0].configured && snapshot.afes[4].configured,
          "requested AFEs are configured");
  Require(snapshot.afes[0].aligned && snapshot.afes[4].aligned, "all AFEs complete alignment");
  Require(snapshot.trigger_mask_low == 1u, "low trigger mask is built");
  Require(snapshot.trigger_mask_high == (1u << 7), "high trigger mask is built");

  std::chrono::nanoseconds observed_configure_duration{0};
  for (size_t index = 1; index < sleeps.size(); ++index) {
    observed_configure_duration += sleeps[index];
  }
  Require(observed_configure_duration == expected_duration,
          "scheduled delays match nominal configure duration");

  backend.set_trigger_counters(39, 101, 7, 2);
  daphne::ReadTriggerCountersRequest counters_request;
  counters_request.add_channels(39);
  const auto counters = backend.read_trigger_counters(counters_request);
  Require(counters.success() && counters.snapshots_size() == 1, "counter read succeeds");
  Require(counters.snapshots(0).record_count() == 101, "counter state is returned");
  Require(backend.read_test_register().value() == 0xDEADBEEF, "test register is compatible");

  auto handlers = daphne_sc::make_emulated_v2_handlers(backend);
  std::string handler_output;
  handlers.at(daphne::MT2_CONFIGURE_FE_REQ)(request.SerializeAsString(), handler_output);
  daphne::ConfigureResponse handler_response;
  Require(handler_response.ParseFromString(handler_output) && handler_response.success(),
          "protocol handler delegates to backend");
  Require(backend.snapshot().configuration_generation == 2,
          "handler configuration mutates the same instance");

  setenv("DAPHNE_TELEMETRY_BOARD_ID", "015", 1);
  daphne::telemetry::v8::ReadTelemetrySnapshotRequest telemetry_request;
  telemetry_request.set_request_sequence(77);
  const auto telemetry = backend.read_telemetry_snapshot(telemetry_request);
  Require(telemetry.success(), "v8 telemetry snapshot succeeds");
  Require(telemetry.schema_major() == 2 && telemetry.schema_minor() == 0,
          "explicit v8 telemetry schema is identified");
  Require(telemetry.schema_source_sha256() == DAPHNE_TELEMETRY_SCHEMA_SHA256,
          "v8 telemetry reports the canonical schema source hash");
  Require(telemetry.board_id() == "015", "v8 telemetry uses the configured board id");
  Require(telemetry.request_sequence() == 77, "v8 telemetry preserves request correlation");
  Require(telemetry.has_telemetry(), "response carries the explicit BoardTelemetry message");
  Require(daphne_sc::telemetry::CatalogSize() == 1370,
          "compiled catalog matches the proposed-v8 HD expansion");
  Require(ValidateExplicitSamples(telemetry.telemetry()) == daphne_sc::telemetry::CatalogSize(),
          "explicit fields expand to the complete board-owned catalog");
  const auto& selector = telemetry.telemetry().spy_trigger_source_selector();
  const auto& inhibit = telemetry.telemetry().spy_trigger_inhibit();
  Require(selector.metadata().quality() == daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD &&
              selector.reading_case() == daphne::telemetry::v8::IntegerSample::kValue &&
              selector.value() == 3,
          "explicit source_selector field carries the emulated firmware value");
  Require(inhibit.metadata().quality() == daphne::telemetry::v8::TELEMETRY_QUALITY_GOOD &&
              inhibit.reading_case() == daphne::telemetry::v8::BooleanSample::kValue &&
              !inhibit.value(),
          "explicit inhibit field carries the emulated firmware value");
  Require(telemetry.telemetry().channels_trigger_record_count_size() == 40,
          "explicit channel field contains all 40 channel instances");
  Require(telemetry.telemetry().hd_mezz_voltage5_v_size() == 5,
          "explicit HD-mezzanine field contains all five AFE instances");

  std::string telemetry_output;
  handlers.at(daphne::MT2_READ_TELEMETRY_SNAPSHOT_REQ)(telemetry_request.SerializeAsString(),
                                                       telemetry_output);
  daphne::telemetry::v8::ReadTelemetrySnapshotResponse telemetry_from_handler;
  Require(
      telemetry_from_handler.ParseFromString(telemetry_output) && telemetry_from_handler.success(),
      "v8 telemetry protocol handler serializes the complete response");

  handlers.at(daphne::MT2_READ_TELEMETRY_SNAPSHOT_REQ)("not protobuf", telemetry_output);
  Require(
      telemetry_from_handler.ParseFromString(telemetry_output) && !telemetry_from_handler.success(),
      "shared v8 handler rejects a malformed protobuf request");

  daphne::ConfigureRequest invalid_request;
  invalid_request.add_channels()->set_id(40);
  const auto invalid_response = backend.configure(invalid_request);
  Require(!invalid_response.success(), "invalid channel is rejected");
  Require(backend.snapshot().phase == BoardPhase::kFailed, "invalid configuration records failure");

  std::cout << "emulated DAPHNE backend tests passed\n";
  return 0;
}
