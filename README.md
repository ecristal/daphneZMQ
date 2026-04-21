# daphne-server

Configuration and monitoring toolkit for the DAPHNE front-end, targeting a Xilinx SoM Kria 260.  
The project contains:

- low-level memory access helpers (`DevMem`) used to peek/poke AXI registers from the PS side;
- a ZeroMQ-based register server (`srcs/srv.cpp`) that exposes simple `read`/`write` commands;
- the main `daphneServer` application (v2-only), which orchestrates AFE, SPI, I²C and trigger primitives and uses Protocol Buffers for configuration exchanges.

## Repository layout

- `srcs/` – core C++ sources; most hardware interactions are implemented here.
- `srcs/protobuf/` – protobuf schemas for higher-level commands.
- `srcs/configurations/` – default runtime configuration snippets.
- `client/`, `bash_scripts/` – helper clients and maintenance scripts.

## Prerequisites

- CMake ≥ 3.10 and a C++17-capable compiler.
- [ZeroMQ](https://zeromq.org/) runtime (`libzmq`) and the `cppzmq` headers.
- [Protocol Buffers](https://protobuf.dev/) compiler and library.
- [CLI11](https://github.com/CLIUtils/CLI11) headers (vendored under `third_party/CLI11/include`).
- `libi2c` (optional; needed when using the I²C features of `daphneServer`).
- OpenMP (optional; enabled automatically if available).

On Ubuntu-like systems the following packages cover the essentials:

```bash
sudo apt install build-essential cmake libzmq3-dev libprotobuf-dev protobuf-compiler \
                 libi2c-dev
```

## Building

```bash
# Fast build (if Ninja is available)
cmake -S . -B build -G Ninja
ninja -C build

# Standard makefiles
# cmake -S . -B build
# cmake --build build --parallel
```

Note: on non-Linux hosts (e.g. macOS), the I²C/SPI backends are stubbed to allow compilation, but hardware access will
not work at runtime. Build on (or for) Linux/Petalinux for deployment.

Minimal source set for building `daphneServer`:

- `CMakeLists.txt`
- `srcs/` (including `srcs/protobuf/*.proto`)
- `third_party/CLI11/include`
- `third_party/cppzmq` (optional; used when `zmq.hpp` is not installed system-wide)

The build produces two main executables:

- `build/daphneServer` – the high-level slow-control application (ControlEnvelopeV2 only).
- `build/daphne_zmq_server` – a lightweight register access server.

## daphneServer (v2-only)

`daphneServer` is a ROUTER-based server that accepts `ControlEnvelopeV2` only. Legacy `ControlEnvelope`
messages are deprecated and ignored.

Transport behavior:

- The server preserves `task_id`, sets `correl_id` to the request `msg_id`, and generates a fresh `msg_id` per response.
- For chunked spybuffer dumps, a single request produces a sequence of responses with the same `task_id`/`correl_id`.

### Usage

```bash
./build/daphneServer --bind tcp://*:9876
```

Optional flags:

- `--disable-monitoring` disables the background I²C monitoring threads.
- `--monitor-period-ms 200` controls monitoring cadence.

Safety knobs:

- `DAPHNE_SKIP_CONFIG_RESET=1` skips the reset/powercycle at the start of configure.
- `DAPHNE_SKIP_ALIGN_AFTER_CONFIGURE=1` skips the auto-align during configure.
- `DAPHNE_MAX_SPYBUFFER_BYTES` caps the non-chunked spybuffer dump response size (default 64 MiB).
- `DAPHNE_MAX_SPYBUFFER_CHUNK_BYTES` caps per-chunk size for chunked dumps (default 64 MiB).

Frontend alignment and access-safety constraints are documented in
`docs/frontend-safety-contract.md`. Keep that file in sync with firmware-side
frontend/control contracts when changing alignment, register use, or optional
block behavior.

Timing-endpoint readiness and clock-source safety constraints are documented in
`docs/endpoint-safety-contract.md`. Keep that file in sync with firmware-side
timing contracts when changing endpoint initialization, readiness checks, or
clock-source behavior.

Target-side compile, service installation, and bring-up validation steps are
documented in `docs/bringup-validation.md`.

Recommended bring-up order on target:

1. configure the external clock chip over I2C
2. load the PL
3. configure the timing endpoint and wait for ready
4. start Hermes and the slow-control server

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

The “one-shot” client `client/configure_fe_min_v2.py` sends a CONFIGURE_FE (V2 envelope) to `daphneServer` and optionally an explicit ALIGN request. The sequence on the server is:

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
- Refuse alignment if `DELAYCTRL_READY` does not assert after reset.
- For each AFE (0–4), scan delay taps to find the longest stable FCLK window, then scan bitslip 0–15 looking for the exact `0x00FF00FF` pattern. The spy snapshot is taken by writing the frontend trigger magic value `0xBABA` and waiting briefly before reading the 32-bit FCLK word.
- After choosing TAP/BITSLIP, perform a short verification sweep and require the expected `0x00FF00FF` pattern to remain stable. Do not report success for an AFE that only hits the target on a single lucky sample.
- Re-enable delay VTC and report TAP/BITSLIP per AFE. When invoked via `configure_fe_min_v2.py -align_afes --full`, the response includes the delay window and the full bitslip scan words to aid debugging.

Important frontend assumptions:

- The frontend deserialize boundary is `16-bit`.
- The required AFE serialization mode is `LSb-first`.
- `DELAYCTRL_READY` is a prerequisite for trusting alignment.
- Delay tap programming is only valid while VTC is disabled.

Tuning knobs:
- Set `DAPHNE_SKIP_CONFIG_RESET=1` to skip the reset/powercycle at the start of configure.
- Set `DAPHNE_SKIP_ALIGN_AFTER_CONFIGURE=1` to skip the auto-align during configure and rely only on the explicit `-align_afes` from the client.

## Cross-compiling for Petalinux (aarch64)

This repository is designed to be built on the target (Petalinux) or cross-compiled using a sysroot.
A minimal cross-compile invocation looks like:

```bash
cmake -S . -B build-peta \
  -DCMAKE_TOOLCHAIN_FILE=toolchains/aarch64-petalinux.cmake \
  -DCMAKE_SYSROOT=/path/to/petalinux/sysroot \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build-peta --parallel
```

For local testing of the produced aarch64 binaries, run them under an emulator (e.g. `qemu-aarch64`) with a matching
rootfs. The easiest workflow is usually to compile in a Petalinux SDK container or on a build VM that has the correct
sysroot and libraries.

## Building on Petalinux from checkout only (`$HOME/daphne-server`)

The default Petalinux flow is self-contained in this checkout and uses a pinned
deps tarball from `deps/deps.lock.cmake`.

```bash
git clone <your-repo-url> daphne-server
cd "$HOME/daphne-server"
./scripts/petalinux_build.sh ./build-petalinux ./deps_tarballs
./build-petalinux/daphneServer --bind tcp://*:9876
```

To create a minimal deployable bundle (binaries + runtime libs copied from this
checkout/build tree), run:

```bash
./scripts/make_deploy_bundle.sh ./build-petalinux ./deploy
./deploy/run_daphneServer.sh --bind tcp://*:9876
```

## Managing the pinned deps tarball

### 1) Create the deps tarball (once, on a reference machine)

On a reference Petalinux machine with a known-good dependency prefix, create a
tarball containing minimal headers/libs/tools:

```bash
cd daphne-server
./scripts/make_deps_tarball_from_prefix.sh /path/to/prefix ./deps_tarballs \
  daphne-deps-petalinux2024.1-aarch64-glibc2.36-protobuf30.1-zeromq4.3.4.tar.gz
```

That script prints a SHA256 and the `set(...)` lines to paste into `deps/deps.lock.cmake` (commit that file).

### 2) Build using the pinned tarball (on any Petalinux machine)

Copy the tarball to the target (or place it in a shared location), then:

```bash
cd "$HOME/daphne-server"
./scripts/petalinux_build.sh ./build-petalinux ./deps_tarballs
./build-petalinux/daphneServer --bind tcp://*:9876
```

The build script fails fast if the pinned tarball is missing or does not match
`deps/deps.lock.cmake`.

## Contributing

Please open merge requests or issues with reproduction steps, expected behaviour,
and board/bitstream details. Continuous improvements around documentation,
automation, and error handling are especially welcome.
