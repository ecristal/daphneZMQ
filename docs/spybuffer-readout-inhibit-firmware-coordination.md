# Spybuffer Trigger Control and Readout Inhibit

## Status and scope

This document is the server-side contract implemented for the firmware branch
`codex/timing-endpoint-ring2k-hermes2-1024`, inspected at firmware commit
`00398dc`. It supersedes the earlier proposal that used independent registers
at `0x9400004C` and `0x94000050`.

The firmware is not modified by this work. The server adapts to the combined
trigger-control register already implemented by that firmware.

Two protections remain complementary:

- timestamp deduplication prevents delivering one captured event twice;
- readout inhibit prevents a new event from overwriting spybuffer BRAM while
  the server copies a waveform.

See also
[Spybuffer Deduplication Verification](spybuffer-deduplication-verification.md).

## Combined register contract

The trigger selector and global readout inhibit share one register.

| Property | Value |
| --- | --- |
| Firmware register | `spy_trigger_ctrl_reg` |
| Physical address | `0x88000034` |
| `FpgaRegDict` relative address | `0x08000034` |
| Server key | `spyTriggerControl` |
| Access | R/W with readback |
| Reset value | `0x00000003` |

| Bits | Server field | Meaning |
| ---: | --- | --- |
| `1:0` | `SOURCE` | Global trigger-source selector |
| `2` | `INHIBIT` | Reject admission of new spybuffer captures while high |
| `2:0` | `CONTROL` | Complete implemented register value |
| `31:3` | — | Reserved |

The source encoding is:

| Value | CLI name | Accepted source |
| ---: | --- | --- |
| `0` | `software` | FRONT_END software-trigger register |
| `1` | `external` | Physical external trigger input |
| `2` | `timing` | Timing endpoint event selected by `adhoc` |
| `3` | `all` | Legacy OR of software, external, and timing sources |

Both fields are global to all 40 channels. A trigger captures every channel,
so neither source selection nor inhibit is configured per channel.

The server always performs field-preserving read-modify-write operations.
Asserting or clearing `INHIBIT` must not alter `SOURCE`, and changing `SOURCE`
must not accidentally clear an active inhibit.

## Safe source transition

The source bits cross from the register clock domain to the acquisition clock
domain. `SpyBuffer::configureTriggerSource` serializes configuration against
acquisition with the global acquisition mutex and performs:

1. read and remember the current source;
2. assert `INHIBIT`, preserving the current source;
3. wait for control CDC settling;
4. write the new `SOURCE`, keeping `INHIBIT` high;
5. wait for control CDC settling;
6. clear `INHIBIT`, preserving the new source;
7. read back and return the configured source.

Firmware requires at least five 62.5 MHz clocks, or 80 ns, around the source
change. The server currently uses 1 microsecond for each control settling
interval. If configuration fails, cleanup attempts to restore the previous
source and clear inhibit.

Changing the source never creates a trigger. Events rejected while a source
is disabled or inhibit is active are discarded, not queued for later replay.

## Protected acquisition sequence

Both normal and chunked dump handlers use
`SpyBuffer::acquireFreshMappedData`. For each waveform it performs:

```text
wait for a fresh timestamp with INHIBIT low
assert INHIBIT while preserving SOURCE
wait for a possible accepted capture to finish
read the frozen timestamp
copy every requested channel under the same global inhibit
verify that the timestamp remained unchanged
clear INHIBIT while preserving SOURCE
repeat for the next waveform
```

The guard is once per global waveform, not once per channel. The FPGA capture
depth is 2048 samples even if the client requests fewer. At 62.5 MHz the store
takes 32.768 microseconds; the server applies a 35 microsecond minimum guard.
`DAPHNE_SPYBUFFER_INHIBIT_GUARD_US` may increase it but values below 35 are
rejected.

The server must never wait for a new trigger while inhibit is high. RAII
cleanup clears inhibit on success, timeout, extraction error, and exception.

At startup, the server probes bit 2 by asserting it, checking readback, waiting
for control settling, and clearing it. A bitstream without the combined
register is rejected before unprotected acquisition can begin.

## Protobuf API

The EnvelopeV2 control API exposes source configuration independently from
waveform acquisition:

| Message type | ID | Payload |
| --- | ---: | --- |
| `MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_REQ` | `326` | `WriteSpyBufferTriggerSourceRequest` |
| `MT2_WRITE_SPYBUFFER_TRIGGER_SOURCE_RESP` | `327` | `WriteSpyBufferTriggerSourceResponse` |
| `MT2_READ_SPYBUFFER_TRIGGER_SOURCE_REQ` | `328` | `ReadSpyBufferTriggerSourceRequest` |
| `MT2_READ_SPYBUFFER_TRIGGER_SOURCE_RESP` | `329` | `ReadSpyBufferTriggerSourceResponse` |

The protobuf enum `SpyBufferTriggerSource` uses the firmware encoding exactly.
The write response contains the verified hardware readback. The separate read
RPC is available for diagnostics and client-side confirmation.

`DumpSpyBuffersRequest.softwareTrigger` is retained. It does not configure the
selector. It only tells the server whether to issue one software-trigger write
for each requested waveform. Clients therefore set it true only when
`SOURCE=software`.

## Client behavior

The supported acquisition and oscilloscope clients configure and verify the
global selector before their first dump:

```text
-trigger_source software
-trigger_source external
-trigger_source timing
-trigger_source all
```

`external` is the client default. The spelling `--trigger-source` is also
accepted. The old `-software_trigger`/`--software-trigger` flag remains as a
deprecated alias for `-trigger_source software`; combining it with another
source is rejected.

Examples:

```bash
python3 client/protobuf_acquire_list_channels.py \
  -ip 193.206.157.36 -port 9876 \
  -foldername output -channel_list 0,1,2 \
  -N 32 -L 2048 -trigger_source external

python3 client/osc.py \
  -ip 193.206.157.36 -port 9876 \
  --channels 0-7 -L 2048 -trigger_source timing
```

For `software`, each dump issues software triggers through the existing
mechanism. For `external`, `timing`, and `all`, dumps wait for accepted hardware
events. Selecting `timing` does not configure the `adhoc` event value; that is
an independent system configuration.

The selector is persistent and global. Concurrent clients must not assume they
can own different sources. Operationally, one acquisition owner should
configure and use the spybuffer at a time.

Clients require Python bindings generated from the same `.proto` as the
server. A missing RPC produces an explicit instruction to rebuild the
bindings rather than silently acquiring with an unknown source. The clients
search the standard build directories and honor an explicit location:

```bash
cmake --build build-petalinux --target daphne_proto_py
export DAPHNE_PROTO_PYTHON_DIR="$PWD/build-petalinux/srcs/protobuf"
```

## Verification

Server-side checks required before hardware acceptance are:

1. register metadata reports address `0x08000034`, `SOURCE[1:0]`, and
   `INHIBIT[2]`;
2. inhibit operations preserve all source values;
3. source changes preserve inhibit until the safe transition completes;
4. invalid source values are rejected;
5. both RPCs return the hardware readback and useful errors;
6. both dump APIs preserve timestamp freshness and temporal coherence;
7. cleanup never leaves inhibit asserted;
8. client configuration is verified before acquisition starts.

The AFE ramp campaign in `client/test_spybuffer_readout_inhibit.py` remains the
temporal-coherence test. Previous testing established a clean readout baseline
on 37 channels through both normal and chunked APIs. Channels 3, 25, and 39
showed deterministic frontend alignment signatures, documented separately in
[AFE Test-pattern Diagnostics](afe-test-pattern-diagnostics.md); those
channel-local faults are not readout-overwrite evidence.

The trigger-source smoke test is `client/test_spybuffer_trigger_source.py`.
It saves the initial source, exercises write/readback of all four values,
acquires through the normal and chunked APIs with software triggers, and
restores the initial source in `finally`:

```bash
DAPHNE_PROTO_PYTHON_DIR="$PWD/build-petalinux/srcs/protobuf" \
python3 client/test_spybuffer_trigger_source.py \
  --ip 193.206.157.36 --port 9876 --route mezz/0 \
  --channels 0-39 --samples 2048 --waveforms 8 --chunk-size 2
```

Use `--selector-only` to test only register configuration. External and timing
event acceptance require the corresponding laboratory stimulus and can be
added with `--hardware-source external`, `timing`, or `all`.
