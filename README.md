# daphneZMQ

Slow-control and monitoring toolkit for the DAPHNE front-end, targeting a Xilinx SoM.  
The project contains:

- low-level memory access helpers (`DevMem`) used to peek/poke AXI registers from the PS side;
- a ZeroMQ-based register server (`srcs/srv.cpp`) that exposes simple `read`/`write` commands;
- the main `DaphneSlowController` high-level application, which orchestrates AFE, SPI, I²C and trigger primitives and uses Protocol Buffers for configuration exchanges.

## Repository layout

- `srcs/` – core C++ sources; most hardware interactions are implemented here.
- `srcs/protobuf/` – protobuf schemas for higher-level commands.
- `srcs/configurations/` – default runtime configuration snippets.
- `client/`, `bash_scripts/` – helper clients and maintenance scripts.

## Prerequisites

- CMake ≥ 3.10 and a C++17-capable compiler.
- [ZeroMQ](https://zeromq.org/) runtime (`libzmq`) and the `cppzmq` headers.
- [Protocol Buffers](https://protobuf.dev/) compiler and library.
- [CLI11](https://github.com/CLIUtils/CLI11) headers (optional, header-only fallback is used).
- `libi2c` (optional; needed when using the I²C features of `DaphneSlowController`).
- OpenMP (optional; enabled automatically if available).

On Ubuntu-like systems the following packages cover the essentials:

```bash
sudo apt install build-essential cmake libzmq3-dev libprotobuf-dev protobuf-compiler \
                 libcli11-dev libi2c-dev
```

## Building

```bash
cmake -S . -B build
cmake --build build --parallel
```

The build produces two main executables:

- `build/DaphneSlowController` – the high-level slow-control application.
- `build/daphne_zmq_server` – a lightweight register access server.

## ZeroMQ register server

The server provides blocking request/reply access to AXI registers. It accepts the
optional bind endpoint as the first argument or via the `DAPHNEZMQ_BIND` env var.
If neither is provided it falls back to `tcp://*:9000`.

### Usage

```bash
# bind to all interfaces on port 9000
./build/daphne_zmq_server

# bind explicitly
./build/daphne_zmq_server tcp://192.168.2.10:9000

# or via environment variable
export DAPHNEZMQ_BIND=tcp://0.0.0.0:6000
./build/daphne_zmq_server
```

Commands use ASCII hex tokens (with or without `0x` prefixes):

```
read <offset>
write <offset> <value>
```

Replies are:

- `OK` for a successful write verification,
- an 8-digit uppercase hex string for `read`,
- or `ERROR: …` with diagnostics.

Offsets are interpreted as byte offsets within the mapped AXI window starting at
`0x4000_0000` by default. Adjust `kAxiBaseAddr` / `kAxiWindowSize` in
`srcs/srv.cpp` if your platform uses a different layout.

## Development notes

- `DevMem` now validates offsets and length arguments and no longer leaks file
  descriptors or mappings when remapping.
- If you add new binaries, prefer reusing the existing CMake targets (e.g. by
  adding to `SOURCES` or creating dedicated executables alongside
  `daphne_zmq_server`).
- For hardware-less testing consider mocking `/dev/mem` access or building with
  a stub.

## Configure + Align (what happens when you run `configure_fe_min_v2.py`)

The “one-shot” client `client/configure_fe_min_v2.py` sends a CONFIGURE_FE (V2 envelope) to `DaphneSlowController` and optionally an explicit ALIGN request. The sequence on the server is:

- CONFIGURE_FE handling (`MT2_CONFIGURE_FE_REQ` → `configureDaphne()`):
  - If `DAPHNE_SKIP_CONFIG_RESET` is unset: reset AFEs and power them on.
  - Program trigger thresholds for the listed channels using `/dev/mem` at `0xA0010000` (stride 0x20) and set trigger enable masks (`0x94000020` low / `0x94000024` high).
  - Program per-channel TRIM/OFFSET DACs (40 channels).
  - Program per-AFE attenuation (VGAIN) and AFE functions (serialized data rate, ADC output format, LPF, PGA clamp/integrator disable, LNA clamp/gain/integrator disable).
  - Reinforce AFE power on.
  - If `DAPHNE_SKIP_ALIGN_AFTER_CONFIGURE` is unset: run `alignAFE()` (see below).
- Optional explicit align: if the client flag `-align_afes` is set, the client sends `MT2_ALIGN_AFE_REQ` after configure, and the server runs `alignAFE()` again and returns TAP/BITSLIP plus scan details.

Alignment logic (`alignAFE()`):
- Reset delay control and SERDES, disable delay VTC.
- For each AFE (0–4), scan delay taps to find the longest stable FCLK window, then scan bitslip 0–15 looking for the exact `0x00FF00FF` pattern. The spy snapshot is taken by writing the frontend trigger magic value `0xBABA` and waiting briefly before reading the 32-bit FCLK word.
- Re-enable delay VTC and report TAP/BITSLIP per AFE. When invoked via `configure_fe_min_v2.py -align_afes --full`, the response includes the delay window and the full bitslip scan words to aid debugging.

Tuning knobs:
- Set `DAPHNE_SKIP_CONFIG_RESET=1` to skip the reset/powercycle at the start of configure.
- Set `DAPHNE_SKIP_ALIGN_AFTER_CONFIGURE=1` to skip the auto-align during configure and rely only on the explicit `-align_afes` from the client.

## Contributing

Please open merge requests or issues with reproduction steps, expected behaviour,
and board/bitstream details. Continuous improvements around documentation,
automation, and error handling are especially welcome.
