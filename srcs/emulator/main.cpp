#include <chrono>
#include <cmath>
#include <iostream>
#include <string>

#include <zmq.hpp>

#include "CLI/CLI.hpp"
#include "emulator/EmulatedDaphneBackend.hpp"
#include "emulator/emulated_handlers.hpp"
#include "server_controller/router_server.hpp"

int main(int argc, char* argv[]) {
  CLI::App app{"Protocol-compatible DAPHNE slow-control emulator"};

  std::string bind_endpoint = "tcp://*:40001";
  double time_scale = 1.0;
  int startup_delay_ms = 0;
  int channel_write_us = 0;
  int afe_write_us = 0;
  bool skip_alignment = false;
  daphne_sc::RouterServerOptions server_options;

  app.add_option("--bind", bind_endpoint, "ZeroMQ bind endpoint")->default_val(bind_endpoint);
  app.add_option("--time-scale", time_scale, "Scale all hardware delays (0 disables waiting)")
      ->default_val(time_scale);
  app.add_option("--startup-delay-ms", startup_delay_ms,
                 "Delay before the slow-control service starts listening")
      ->default_val(startup_delay_ms);
  app.add_option("--channel-write-us", channel_write_us, "Delay for each channel DAC write")
      ->default_val(channel_write_us);
  app.add_option("--afe-write-us", afe_write_us, "Delay for each AFE programming operation")
      ->default_val(afe_write_us);
  app.add_flag("--skip-alignment", skip_alignment, "Skip the post-configuration AFE alignment delay");
  app.add_option("--sndhwm", server_options.sndhwm, "ZMQ SNDHWM")
      ->default_val(server_options.sndhwm);
  app.add_option("--rcvhwm", server_options.rcvhwm, "ZMQ RCVHWM")
      ->default_val(server_options.rcvhwm);
  app.add_option("--sndbuf", server_options.sndbuf, "ZMQ SNDBUF bytes")
      ->default_val(server_options.sndbuf);

  try {
    app.parse(argc, argv);
  } catch (const CLI::ParseError& error) {
    return app.exit(error);
  }

  if (!std::isfinite(time_scale) || time_scale < 0.0 || startup_delay_ms < 0 ||
      channel_write_us < 0 || afe_write_us < 0) {
    std::cerr << "Time scale and emulation delays must be finite and non-negative\n";
    return 2;
  }

  daphne_sc::emulator::TimingProfile timing;
  timing.time_scale = time_scale;
  timing.startup_delay = std::chrono::milliseconds(startup_delay_ms);
  timing.channel_dac_write = std::chrono::microseconds(channel_write_us);
  timing.afe_program = std::chrono::microseconds(afe_write_us);
  timing.auto_align = !skip_alignment;

  daphne_sc::emulator::EmulatedDaphneBackend backend(timing);
  backend.boot();

  std::cout << "Starting DAPHNE slow-control emulator\n"
            << "Bind: " << bind_endpoint << "\n"
            << "Time scale: " << time_scale << "\n"
            << "Alignment: " << (timing.auto_align ? "enabled" : "disabled") << "\n";

  zmq::context_t context(1);
  const auto handlers = daphne_sc::make_emulated_v2_handlers(backend);
  daphne_sc::run_router_server(context, bind_endpoint, handlers, server_options);
  return 0;
}
