# Spybuffer Deduplication Verification

## Contract

The server treats the four 16-bit FPGA timestamp banks as the identity of a
captured spybuffer event:

| Bank | Register offset | Physical address |
| --- | ---: | ---: |
| `timestamp0` | `0x1002D000` | `0x9002D000` |
| `timestamp1` | `0x1002E000` | `0x9002E000` |
| `timestamp2` | `0x1002F000` | `0x9002F000` |
| `timestamp3` | `0x10030000` | `0x90030000` |

The response timestamp is packed as:

```text
timestamp0 | timestamp1 << 16 | timestamp2 << 32 | timestamp3 << 48
```

Each waveform returned by `DumpSpyBuffersResponse` or
`DumpSpyBuffersChunkResponse` has one corresponding `uint64` entry in the new
`timestamps` field. Existing Protobuf clients remain compatible because the
field numbers are new and optional.

The first hardware-triggered acquisition uses the current FPGA timestamp as its
baseline and waits for a newer trigger, so it cannot return stale pre-request
data. Later requests wait only while the current timestamp equals the last
delivered timestamp; an already-newer snapshot can be consumed immediately. A
software-triggered acquisition reads its baseline before issuing `0xBABA` and
waits for that timestamp to advance.

The timestamp is a deduplication cursor, not a freeze condition. The server does
not require it to remain stable before or during the spybuffer copy. This keeps
the original maximum-throughput behavior: when triggers are faster than
extraction, every delivered snapshot has a newer timestamp but intermediate
triggers may be skipped. The delivered rate is therefore bounded by:

```text
min(trigger rate, server extraction and transport capacity)
```

## Build and deploy

Rebuild both the C++ server and Python bindings from the same schema. The normal
CMake build generates the Python files under `<build>/srcs/protobuf`.

For a slow trigger, configure the per-waveform server timeout to exceed several
trigger periods. For example, for a 0.2 Hz trigger:

```bash
export DAPHNE_SPYBUFFER_TRIGGER_TIMEOUT_MS=20000
export DAPHNE_SPYBUFFER_TIMESTAMP_POLL_US=100
./build-petalinux/daphneServer --bind tcp://*:40001
```

`DAPHNE_SPYBUFFER_TRIGGER_TIMEOUT_MS=0` disables the server timeout. Use it only
for a dedicated acquisition test because the current ROUTER handles requests
synchronously.

`DAPHNE_SPYBUFFER_TIMESTAMP_POLL_US` is used only while the timestamp is equal
to the last delivered value. A continuously advancing timestamp does not incur
the polling sleep.

## Continuous generator test

Configure the external signal generator first, then run the client. It requests
one waveform per RPC indefinitely and stops only on `Ctrl+C`:

```bash
DAPHNE_BUILD_DIR=build-petalinux \
python3 client/test_spybuffer_deduplication.py \
  --ip 10.73.137.161 \
  --port 40001 \
  --route mezz/0 \
  --channels 0,1,2,3 \
  --samples 2048 \
  --expected-rate-hz 10 \
  --timestamp-clock-hz 62500000 \
  --tolerance-percent 5
```

`--timestamp-clock-hz 62500000` assumes a 62.5 MHz timestamp tick. Override it
if the loaded firmware uses a different timestamp clock.

The periodic output reports:

- `fpga`: rate calculated from FPGA timestamp deltas;
- `host`: response arrival rate measured with the host monotonic clock;
- `error`: rolling FPGA-rate error relative to the generator setting;
- `dup_ts`: equal adjacent timestamps, which is a deduplication failure;
- `nonmono`: timestamp regressions other than normal 64-bit wrap;
- `rate_outliers`: individual intervals outside the configured tolerance;
- `same_data`: identical waveform payloads, reported but not treated as an
  error because two distinct physical triggers can legitimately have identical
  ADC samples;
- `timeouts` and `errors`: transport or server acquisition failures.

For a bounded smoke test, add `--max-waveforms 100`. The default is `0`, which
runs indefinitely.

## Acceptance criteria

Run each required generator rate long enough to fill several rolling windows.
The recommended matrix is:

| Trigger rate | Channels | Samples | Minimum duration |
| ---: | --- | ---: | ---: |
| 0.2 Hz | one and four | 2048 | 10 minutes |
| 1 Hz | one and four | 2048 | 5 minutes |
| 10 Hz | one and four | 2048 | 2 minutes |
| 100 Hz | one and four | 2048 | 2 minutes |

Accept a run when:

1. `dup_ts=0` and `nonmono=0` for the complete run;
2. `timeouts=0` and `errors=0` after startup;
3. when the trigger rate is below extraction capacity, the rolling FPGA rate
   stays within the selected tolerance after the window fills;
4. each response contains exactly one timestamp per waveform;
5. each multichannel response has one deduplication timestamp.

Above the extraction capacity, `fpga` reports the delivered snapshot rate, not
the source trigger rate. A lower rate and skipped timestamp intervals are
expected; duplicates, non-monotonic timestamps, timeouts, and request errors are
still failures.

If the FPGA rate differs from the generator by a constant scale factor, verify
`--timestamp-clock-hz` before diagnosing trigger loss.

## Repository-side verification performed

The following checks do not replace the hardware generator test:

- Protobuf generation confirmed `DumpSpyBuffersResponse.timestamps` as field 8
  and `DumpSpyBuffersChunkResponse.timestamps` as field 12.
- The continuous client passed Python syntax, CLI, channel parser, and synthetic
  10 Hz timestamp-rate helper checks.
- An end-to-end local ROUTER simulation returned five two-channel waveforms at
  20 Hz; the real client reported exactly 20 Hz from FPGA timestamps with zero
  duplicates, regressions, outliers, timeouts, or request errors.
- The available `hdmezz_driver_unit` CTest passed in a clean server-disabled
  Windows build.
- `git diff --check` passed.

A complete `daphneServer` build was not available on the Windows workstation
because the AArch64/PetaLinux compiler, ARM NEON headers, and target sysroot are
not installed. Compile the implementation with the deployment toolchain before
installing it on DAPHNE.
