#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include <zmq.hpp>

#include "CLI/CLI.hpp"
#include "Daphne.hpp"
#include "server_controller/handlers.hpp"
#include "server_controller/monitoring.hpp"
#include "server_controller/router_server.hpp"

int main(int argc, char* argv[]) {
  CLI::App app{"daphneServer"};

  std::string bind_endpoint = "tcp://*:9876";
  bool disable_monitoring = false;
  int monitor_period_ms = 200;

  daphne_sc::RouterServerOptions server_opts;

  app.add_option("--bind", bind_endpoint, "ZeroMQ bind endpoint")->default_val(bind_endpoint);
  app.add_flag("--disable-monitoring", disable_monitoring, "Disable background I2C monitoring threads");
  app.add_option("--monitor-period-ms", monitor_period_ms, "Monitoring period in milliseconds")
      ->default_val(monitor_period_ms);

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

  zmq::context_t context(1);
  Daphne daphne;

  std::vector<std::thread> monitor_threads;
  if (!disable_monitoring) {
    daphne_sc::MonitoringOptions opts;
    opts.period = std::chrono::milliseconds(monitor_period_ms);
    monitor_threads = daphne_sc::start_monitoring(daphne, opts);
  }

  std::cout << "Starting daphneServer\n";
  std::cout << "Bind: " << bind_endpoint << "\n";
  if (disable_monitoring) {
    std::cout << "Monitoring: disabled\n";
  } else {
    std::cout << "Monitoring period: " << monitor_period_ms << " ms\n";
  }

  const auto handlers = daphne_sc::make_v2_handlers();
  daphne_sc::run_router_server(context, bind_endpoint, daphne, handlers, server_opts);

  for (auto& t : monitor_threads) {
    if (t.joinable()) t.join();
  }

  return 0;
}
