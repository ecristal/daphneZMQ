#include <cmath>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include <zmq.hpp>

#include "CLI/CLI.hpp"
#include "Daphne.hpp"
#include "emulator/EmulatedDaphneBackend.hpp"
#include "emulator/emulated_handlers.hpp"
#include "server_controller/handlers.hpp"
#include "server_controller/monitoring.hpp"
#include "server_controller/router_server.hpp"
#include "server_controller/spybuffer_chunker.hpp"

int main(int argc, char* argv[]) {
  CLI::App app{"daphneServer"};

  std::string bind_endpoint = "tcp://*:9876";
  std::string backend_name = "hardware";
  bool disable_monitoring = false;
  int monitor_period_ms = 200;
  double emulation_time_scale = 1.0;
  int emulation_startup_delay_ms = 0;
  int emulation_channel_write_us = 0;
  int emulation_afe_write_us = 0;

  daphne_sc::RouterServerOptions server_opts;

  app.add_option("--bind", bind_endpoint, "ZeroMQ bind endpoint")->default_val(bind_endpoint);
  app.add_option("--backend", backend_name, "Slow-control backend: hardware or emulator")
      ->default_val(backend_name);
  app.add_flag("--disable-monitoring", disable_monitoring, "Disable background I2C monitoring threads");
  app.add_option("--monitor-period-ms", monitor_period_ms, "Monitoring period in milliseconds")
      ->default_val(monitor_period_ms);
  app.add_option("--emulation-time-scale", emulation_time_scale,
                 "Scale all emulated hardware delays (0 disables waiting)")
      ->default_val(emulation_time_scale);
  app.add_option("--emulation-startup-delay-ms", emulation_startup_delay_ms,
                 "Delay before the emulated slow-control service becomes available")
      ->default_val(emulation_startup_delay_ms);
  app.add_option("--emulation-channel-write-us", emulation_channel_write_us,
                 "Delay for each emulated channel DAC write")
      ->default_val(emulation_channel_write_us);
  app.add_option("--emulation-afe-write-us", emulation_afe_write_us,
                 "Delay for each emulated AFE programming operation")
      ->default_val(emulation_afe_write_us);

  app.add_option("--sndhwm", server_opts.sndhwm, "ZMQ SNDHWM")->default_val(server_opts.sndhwm);
  app.add_option("--rcvhwm", server_opts.rcvhwm, "ZMQ RCVHWM")->default_val(server_opts.rcvhwm);
  app.add_option("--sndbuf", server_opts.sndbuf, "ZMQ SNDBUF bytes")->default_val(server_opts.sndbuf);
  app.add_option("--max-envelope-bytes", server_opts.max_envelope_bytes, "Max incoming envelope bytes")
      ->default_val(server_opts.max_envelope_bytes);

  try {
    app.parse(argc, argv);
  } catch (const CLI::ParseError& e) {
    return app.exit(e);
  }

  if (backend_name != "hardware" && backend_name != "emulator") {
    std::cerr << "Invalid --backend '" << backend_name << "' (expected hardware or emulator)\n";
    return 2;
  }
  if (!std::isfinite(emulation_time_scale) || emulation_time_scale < 0.0 ||
      emulation_startup_delay_ms < 0 ||
      emulation_channel_write_us < 0 || emulation_afe_write_us < 0) {
    std::cerr << "Emulation delays and time scale must be non-negative\n";
    return 2;
  }

  zmq::context_t context(1);
  std::unique_ptr<Daphne> hardware;
  std::unique_ptr<daphne_sc::SlowControlBackend> emulated_backend;
  std::unordered_map<daphne::MessageTypeV2, daphne_sc::V2Handler> handlers;
  std::unordered_map<daphne::MessageTypeV2, daphne_sc::V2StreamingHandler> streaming_handlers;

  if (backend_name == "hardware") {
    hardware = std::make_unique<Daphne>();
    handlers = daphne_sc::make_v2_handlers(*hardware);
    streaming_handlers[daphne::MT2_DUMP_SPYBUFFER_CHUNK_REQ] =
        [&hardware](const std::string& input, const daphne_sc::V2ResponseSink& send_response) {
          daphne::DumpSpyBuffersChunkRequest request;
          if (!request.ParseFromString(input)) {
            daphne::DumpSpyBuffersChunkResponse response;
            response.set_success(false);
            response.set_message("Bad DumpSpyBuffersChunkRequest payload");
            response.set_isfinal(true);
            send_response(response.SerializeAsString());
            return;
          }
          try {
            daphne_sc::for_each_spybuffer_chunk(
                request, *hardware,
                [&send_response](const daphne::DumpSpyBuffersChunkResponse& response) {
                  send_response(response.SerializeAsString());
                });
          } catch (const std::exception& error) {
            daphne::DumpSpyBuffersChunkResponse response;
            response.set_success(false);
            response.set_message(std::string("Chunked dump failed: ") + error.what());
            response.set_isfinal(true);
            send_response(response.SerializeAsString());
          }
        };
  } else {
    daphne_sc::emulator::TimingProfile timing;
    timing.time_scale = emulation_time_scale;
    timing.startup_delay = std::chrono::milliseconds(emulation_startup_delay_ms);
    timing.channel_dac_write = std::chrono::microseconds(emulation_channel_write_us);
    timing.afe_program = std::chrono::microseconds(emulation_afe_write_us);
    emulated_backend = std::make_unique<daphne_sc::emulator::EmulatedDaphneBackend>(timing);
    handlers = daphne_sc::make_emulated_v2_handlers(*emulated_backend);
    disable_monitoring = true;
    emulated_backend->boot();
  }

  std::vector<std::thread> monitor_threads;
  if (!disable_monitoring && hardware) {
    daphne_sc::MonitoringOptions opts;
    opts.period = std::chrono::milliseconds(monitor_period_ms);
    monitor_threads = daphne_sc::start_monitoring(*hardware, opts);
  }

  std::cout << "Starting daphneServer\n";
  std::cout << "Bind: " << bind_endpoint << "\n";
  std::cout << "Backend: " << backend_name << "\n";
  if (disable_monitoring) {
    std::cout << "Monitoring: disabled\n";
  } else {
    std::cout << "Monitoring period: " << monitor_period_ms << " ms\n";
  }

  daphne_sc::run_router_server(context, bind_endpoint, handlers, server_opts, streaming_handlers);

  for (auto& t : monitor_threads) {
    if (t.joinable()) t.join();
  }

  return 0;
}
