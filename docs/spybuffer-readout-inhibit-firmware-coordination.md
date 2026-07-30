# Spybuffer Readout Inhibit: Firmware Coordination Contract

## Status

This document defines the implemented contract between `daphneZMQ` and
`daphne-firmware` for protecting spybuffer data while the server copies a
captured waveform.

The firmware implementation first appears in commit `f0d48d6` on branch
`ecristal/feature/spybuffer_self_triggering_guards`. Register and module
documentation were added in commits `ee7a9c6` and `14b8012`. The STUFF register
block now ends at physical address `0x9400004C`.

The server implements the matching register and protected-copy sequence in
`FpgaRegDict.cpp` and `SpyBuffer::acquireFreshMappedData`. A loaded bitstream
without working readback at `0x9400004C` is rejected when the server attempts
to assert the inhibit.

This work complements
[Spybuffer Deduplication Verification](spybuffer-deduplication-verification.md).
Deduplication and readout inhibition solve different problems:

- deduplication prevents delivery of the same captured event twice;
- readout inhibition prevents a newer trigger from replacing spybuffer
  contents while an event is being copied.

## Problem statement

Each spybuffer captures 2048 16-bit samples after accepting a trigger. The
current `spybuff` FSM progresses through `wait4trig`, `store`, and
`wait4done`. A trigger is ignored while the FSM is storing, but a later trigger
can start another complete capture as soon as the FSM returns to
`wait4trig`.

The server waits for a fresh timestamp and then copies every requested channel
from the memory-mapped spybuffer. The server mutex prevents two server threads
from reading concurrently, but it cannot stop the FPGA from accepting another
trigger. At high trigger rates, a new capture can therefore overwrite part of
the BRAM while the ARM is still copying it, producing a waveform assembled
from different events.

The timestamp used for deduplication is an event cursor. It is not currently a
hardware freeze condition.

## Register contract

The first free aligned offset in the current STUFF register bank is `0x4C`.
The previous experimental implementation used `0x2C`; that address must not be
reused because the current firmware maps `st_config_reg` there.

| Property | Required value |
| --- | --- |
| Firmware register name | `spy_readout_inhibit_reg` |
| STUFF offset | `0x4C` |
| Physical address | `0x9400004C` |
| `FpgaRegDict` relative address | `0x1400004C` |
| Width | 1 bit |
| Access | R/W |
| Reset value | `0` |
| Server dictionary key | `spyReadoutInhibit` |
| Server field name | `INHIBIT` |

Bit definition:

| Bits | Name | Access | Meaning |
| ---: | --- | --- | --- |
| `0` | `INHIBIT` | R/W | `0`: triggers may start a new spybuffer capture. `1`: no new spybuffer capture may start. |
| `31:1` | Reserved | R/O as zero | Writes are ignored and reads return zero. |

The register is global to the complete 40-channel spybuffer bank. A request
containing only a subset of channels still inhibits capture for all 40
channels. There is no per-channel inhibit, because one trigger starts the
capture for every channel.

A successful full-word write of `1` followed by a read must return
`0x00000001`. A successful write of `0` followed by a read must return
`0x00000000`. This readback is required so the server can reject an
incompatible firmware instead of silently running without protection.

The STUFF AXI implementation currently accepts register updates only when
`WSTRB="1111"`. The new register must preserve that behavior.

## Required firmware behavior

`INHIBIT=1` controls admission of future captures. It must not reset the
spybuffer FSM, clear memory, stop an in-progress `store`, or directly gate the
BRAM write-enable signal.

The required trigger equation in the acquisition clock domain is:

```vhdl
spy_trigger_o <=
  (frontend_trigger_i or timing_trigger_s) and
  not spy_readout_inhibit_sync;
```

Both trigger sources must be inhibited:

- the frontend trigger path, including the AXI software trigger;
- the timing-system trigger selected by `adhoc_i`.

Diagnostic signals that describe the raw timing trigger may remain
uninhibited. Only the trigger delivered to `spybuffers` must be gated.

Triggers received while the inhibit is active are discarded. They are not
queued and must not be replayed when the inhibit is released. This intentional
loss is the readout dead time.

If a trigger was accepted immediately before the inhibit became active, that
capture must finish normally. The buffer becomes safe to read after at most one
complete 2048-sample capture plus clock-domain crossing latency.

All spybuffer instances receive the same trigger and therefore share one
logical capture interval. Any future `capture_busy` or `capture_done` status
must also be global, not replicated per channel.

## Clock-domain crossing

The STUFF register is written in the AXI clock domain; `stuff.vhd` documents
`S_AXI_ACLK` as 100 MHz. The spy trigger and capture FSM operate in the
acquisition clock domain, normally 62.5 MHz. The inhibit level must therefore
cross clock domains explicitly.

The minimum implementation is a two-flop level synchronizer in the acquisition
clock domain:

```text
ARM write at 0x9400004C
        |
        v
STUFF AXI register (100 MHz)
        |
        v
two-flop level synchronizer
        |
        v
trigger gate (acquisition clock)
        |
        v
spybuffers
```

The synchronizer registers must reset to `0` and should carry the appropriate
`ASYNC_REG` attributes. Combinational use of the asynchronous AXI-domain
register in the trigger equation is not acceptable.

Without a firmware completion status, the server must allow for synchronizer
latency plus a worst-case full capture before reading. The conservative minimum
guard is:

```text
Tguard >= Tcdc,max + Ncapture * Tclock + Tfsm
```

`Ncapture` is the number of samples written by the FPGA, not the number
requested by the client. With the current fixed depth, `Ncapture=2048` even
when the client requests fewer samples.

For a 62.5 MHz acquisition clock:

```text
Tclock   = 16 ns
Tcapture = 2048 * 16 ns = 32.768 microseconds
```

The server guard must therefore be slightly greater than 32.768 microseconds
after accounting for the synchronizer, FSM latency, and implementation margin.
It must be calculated from the minimum supported acquisition-clock frequency;
`100 microseconds` is not part of the contract.

The current server uses a 35 microsecond guard:

```text
ceil(2048 * 1 second / 62.5 MHz) + 2 microseconds margin
= 33 microseconds + 2 microseconds
= 35 microseconds
```

`DAPHNE_SPYBUFFER_INHIBIT_GUARD_US` may increase this interval for a particular
deployment. Values below 35 are rejected because the firmware does not yet
provide a completion status that would make a shorter wait safe.

The preferred optimization is a global status indicating that the synchronized
inhibit is active and/or that the capture FSM is busy. The server could then
wait only for the actual remaining write time instead of applying a complete
fixed guard to every waveform. These status bits are not part of the mandatory
first revision.

## Throughput model

At high trigger rates, the protected acquisition cycle is approximately:

```text
Tcycle = Tcapture_remaining + Tcopy + Tregister_control
Rmax   = 1 / Tcycle
```

Waiting for an in-progress capture to finish is required for correctness and
overlaps work the FPGA must perform anyway. A blind full-capture guard becomes
additional overhead when the capture had already completed before inhibit was
asserted. A global `capture_busy` or `capture_done` status is the intended way
to remove that unnecessary delay.

No delay is applied once per channel. The guard is evaluated once for the
global event, followed by copying all requested channels under the same
inhibit interval.

## Expected RTL propagation

The register value originates in STUFF but is consumed in the spy trigger
plane. The firmware change is therefore expected to propagate a level through
the following hierarchy:

1. `rtl/isolated/subsystems/control/legacy_stuff_selftrigger_register_bank.vhd`
   - add offset `0x4C` (`"1001100"`);
   - add a one-bit register with reset value `0`;
   - implement full-word write and zero-extended readback;
   - expose `spy_readout_inhibit_o`.
2. `ip_repo/daphne_ip/rtl/config/stuff.vhd`
   - expose the new output from the STUFF AXI slave;
   - connect the register-bank output.
3. `rtl/isolated/subsystems/analog/k26c_board_analog_control_plane.vhd`
   - propagate the STUFF output to the board shell.
4. `rtl/isolated/tops/k26c_board_shell.vhd`
   - declare and route the inhibit signal from the analog control plane to the
     spy capture plane.
5. `rtl/isolated/subsystems/spy/k26c_board_spy_capture_plane.vhd`
   - pass the inhibit request to the trigger plane.
6. `rtl/isolated/subsystems/spy/k26c_board_spy_trigger_plane.vhd`
   - synchronize the level into `clock_i`;
   - gate the combined frontend/timing trigger.

The legacy compatibility path should remain behaviorally aligned:

- `rtl/isolated/subsystems/spy/legacy_spy_capture_bridge.vhd`;
- `rtl/isolated/subsystems/control/legacy_spy_trigger_bridge.vhd`.

If those entities remain build or test targets, add the inhibit port and the
same trigger-gating semantics rather than leaving two different contracts.

The public firmware memory map must add the following STUFF row:

| Offset | Address | Register | Size | Access | Default | Description |
| ---: | ---: | --- | ---: | --- | ---: | --- |
| `0x4C` | `0x9400004C` | `spy_readout_inhibit_reg` | 1b | R/W | `0x0` | Prevent new spybuffer captures while ARM readout is active. |

## Server integration sequence

Both normal and chunked dump paths already call
`SpyBuffer::acquireFreshMappedData`. The inhibit should be implemented there
once so the two APIs cannot diverge.

For each available waveform, the server must perform this protected-copy
sequence:

1. Write `INHIBIT=1`.
2. Read the register back and require `INHIBIT=1`.
3. Wait until an in-progress global capture is complete:
   - preferably, wait for a future global `CAPTURE_BUSY=0`; or
   - in the first revision, wait the calculated conservative guard interval.
4. Read the timestamp. This is the frozen event identity returned to the
   client.
5. Copy every requested channel while keeping the global inhibit asserted.
6. Write `INHIBIT=0` in cleanup code that runs on success and exception.
7. Optionally read back zero.
8. If another waveform is requested, wait with inhibit low until the existing
   deduplication mechanism observes a timestamp different from the frozen
   timestamp, then repeat from step 1.

In compact form:

```text
INHIBIT high
wait for the current write to finish
read frozen timestamp
copy all requested channels
INHIBIT low
wait for the next trigger through timestamp deduplication
repeat
```

The server must never wait for the next trigger while inhibit is high. Such a
sequence would deadlock because firmware is required to reject all new
spybuffer triggers during the inhibit interval.

On the first hardware-triggered request, the server records the timestamp
present at request entry as its baseline and waits for that timestamp to
advance before asserting inhibit. It must not return a pre-request snapshot.
On later requests, a current timestamp that already differs from the last
delivered timestamp may be accepted immediately.

The inhibit scope is one global waveform, including all requested channels. It
must not remain asserted while waiting for the next timestamp, while a
completed chunk waits in the transport queue, or while the ROUTER sends data to
the client.

The cleanup path should use RAII or an equivalent scope guard. No timeout,
allocation failure, extraction exception, or client disconnect may leave the
hardware inhibited.

On server startup, and before accepting the first spybuffer request, software
should write `0` defensively. Firmware reset must independently guarantee the
same default.

## Software-trigger sequence and caveat

For a software-triggered request, `0xBABA` must be issued while inhibit is low.
The server then waits for the timestamp to advance through the existing
deduplication mechanism and begins the protected-copy sequence by asserting
inhibit. This preparation is required before the first waveform and is repeated
after releasing inhibit when another waveform is requested.

Under simultaneous external trigger activity, the snapshot frozen after this
sequence can be newer than the software-triggered event.

This does not violate waveform-coherence or deduplication requirements, but it
means `softwareTrigger=true` cannot yet guarantee exclusive attribution to the
AXI-generated trigger while external triggers are active.

If exclusive attribution becomes a requirement, firmware must preserve source
identity and support either:

- inhibiting timing/external triggers while allowing one software trigger; or
- an atomic "allow one trigger, then inhibit" handshake.

That extension is outside the mandatory first revision and must not be inferred
from the single `INHIBIT` bit.

## Firmware verification

### Register-bank tests

Extend `tests/logic/stuff_axi_smoke_tb.vhd` to verify:

1. reset produces register readback `0` and output `0`;
2. a full-strobe write of `1` produces readback and output `1`;
3. a full-strobe write of `0` clears both;
4. partial-strobe writes do not modify the register;
5. reserved bits read as zero;
6. neighboring registers at offsets `0x48` and earlier retain their current
   behavior.

### Trigger-plane tests

Extend the trigger-plane smoke tests to cover both frontend and timing sources:

| Inhibit | Trigger source | Expected `spy_trigger_o` |
| ---: | --- | ---: |
| `0` | frontend | `1` |
| `0` | timing/adhoc | `1` |
| `1` | frontend | `0` |
| `1` | timing/adhoc | `0` |

Also verify:

- the synchronized inhibit resets inactive;
- activation and release occur only on acquisition-clock edges;
- a trigger pulse entirely contained in the inhibit interval is not replayed;
- release with both trigger sources low does not create a spurious pulse.

### Capture integration test

An integration test around `spybuffers` must demonstrate:

1. a trigger accepted before inhibit activation completes its full 2048-sample
   store;
2. later triggers do not start another capture while inhibited;
3. BRAM contents and timestamp remain unchanged throughout a simulated read
   interval;
4. clearing the inhibit permits a later trigger to start a new capture.

## Joint hardware acceptance

The hardware campaign must verify three independent properties:

1. freshness: a captured timestamp is not delivered twice;
2. temporal coherence: one waveform does not contain samples from two
   different captures;
3. channel identity: every sample returned as channel `c` belongs to channel
   `c`, without complete swaps or temporary channel mixing.

The existing deduplication client covers the first property. The following two
campaigns remain pending for temporal coherence and channel identity.

### Pending AFE ramp continuity campaign

Use the AFE5808A internal ramp as the deterministic waveform:

- set `SYNC_PATTERN` (`register 10[8]`) to `1` on all five AFEs;
- set `TEST_PATTERN_MODES` (`register 2[15:13]`) to `7` on all five AFEs;
- acquire all requested samples as unsigned 14-bit values;
- require every adjacent pair in every channel to satisfy:

```text
(sample[n + 1] - sample[n]) modulo 16384 = 1
```

This relation includes the valid `0x3FFF -> 0x0000` ramp wrap. Any other
transition is a temporal discontinuity and must report the channel, waveform,
and first failing sample.

Run this check through both normal and chunked APIs for one channel and all 40
channels using the trigger-rate matrix below. Choose trigger periods that do
not advance the free-running ramp by an integer multiple of 16384 samples, as
that coincidence could hide an overwrite boundary.

The test must restore `TEST_PATTERN_MODES=0` and `SYNC_PATTERN=0` in cleanup
code even after a timeout or client exception.

The automated smoke test is available at
`client/test_spybuffer_readout_inhibit.py`. Its default configuration exercises
four software-triggered waveforms through both normal and chunked APIs, using
all 40 channels and 2048 samples. It requires the Python `pyzmq` and
`protobuf` packages plus bindings generated from the same schema as the
server:

Before running it, configure and align the frontend normally. In particular,
the server unpacker and firmware expect the AFE5808A 16x serialized,
14-bit, LSB-first interface (`SERIALIZED_DATA_RATE=1`,
`ADC_RESOLUTION_RESET=0`, and `LSB_MSB_FIRST=0`). The smoke test changes only
the test-pattern fields; it does not replace frontend initialization or AFE
alignment.

```bash
DAPHNE_BUILD_DIR=build-petalinux \
python3 client/test_spybuffer_readout_inhibit.py \
  --ip 10.73.137.161 \
  --port 40001 \
  --route mezz/0
```

Use `--hardware-trigger` for the external trigger-rate campaign. The script
enables and validates the AFE ramp and restores normal AFE output in a
`finally` cleanup path. `--keep-ramp-enabled` is available only for an
intentional diagnostic session.

An initial reduced hardware run with one software-triggered waveform and 256
samples passed 37 of 40 channels and reported:

- channel 3: 129 failures dominated by deltas `+3` and `-1`, consistent with
  an alternating bit-1 error;
- channel 25: all 255 transitions failed, dominated by deltas `+257` and
  `-255`, consistent with a bit-8 error plus less frequent additional errors;
- channel 39: two failures with deltas `+33` and `-31`, consistent with a
  bit-5 error;
- zero duplicate or non-monotonic timestamp failures.

These deterministic, channel-local bit errors are a frontend
deserialization/alignment baseline failure, not evidence of an overwrite
during inhibited readout. Full 40-channel acceptance is blocked until this
baseline is clean. Readout-inhibit behavior may be investigated provisionally
with channels `0-2,4-24,26-38`, while keeping the full-channel test pending.

A subsequent provisional run over those 37 clean channels passed both normal
and chunked APIs with four software-triggered 2048-sample waveforms per API:
`605912` adjacent ramp transitions were checked with zero ramp or timestamp
failures. This establishes a clean low-contention server/readout baseline. It
does not yet validate inhibit behavior under concurrent triggers because the
server controls the software-trigger cadence.

The first external-trigger campaign requested 32 waveforms through each API.
The normal API returned stale pre-ramp data as its first waveform and reported
`67711` discontinuities distributed across all 37 requested channels; its
later data was consistent with the ramp. All `2423648` chunked transitions
then passed. The snapshot was new relative to the server's previous delivery
cursor but had been captured before the client enabled the ramp. The smoke
client now primes the hardware-trigger cursor by acquiring and discarding one
snapshot after changing the AFE test-pattern configuration. Independently, the
server now uses the request-entry timestamp as its baseline when no previous
delivery cursor exists, so a true first hardware request cannot return an
unknown boot-time snapshot. A repeat hardware run with both corrections
remains pending.

The synchronized ramp is intentionally identical across the eight channels of
one AFE. It can prove temporal continuity, but it cannot by itself detect a
segment copied from the wrong channel.

### Pending channel-identity campaign

Channel identity must therefore be tested separately in normal ADC mode:

1. Establish the static physical-to-server mapping by stimulating one physical
   input at a time and requiring activity only on the expected server channel.
2. Feed a common waveform, or a common DC level, to the channels under test.
3. Enable `CHANNEL_OFFSET_SUBSTRACTION_ENABLE` and configure a sufficiently
   separated `OFFSET_CHx` value for every channel to create a unique channel
   tag. Save and restore all original register values.
4. Build a low-rate reference for each channel and classify the source of each
   sample window during the high-rate acquisition.
5. Report separately:
   - a complete channel permutation;
   - a temporary interval attributed to another channel;
   - samples that match no known channel signature.

The tag spacing and classification tolerance must be derived from measured
noise. Classification should use short windows as well as whole-waveform
statistics so that a temporary mix is not hidden by the waveform average.

Do not assume that `INVERT_CHANNELS` or per-channel offset/gain processing
modifies the AFE test ramp. The channel-tag campaign uses the normal ADC data
path and remains separate from the internal-ramp campaign.

The recommended matrix is:

| Trigger rate | Channels | Samples | Expected result |
| ---: | --- | ---: | --- |
| 0.2 Hz | 1 and 40 | 2048 | No duplicates or cut waveforms |
| 10 Hz | 1 and 40 | 2048 | No duplicates or cut waveforms |
| 100 Hz | 1 and 40 | 2048 | No duplicates or cut waveforms |
| Above copy capacity | 40 | 2048 | Events may be skipped; returned waveforms remain coherent |

For diagnostic builds, read the four timestamp banks immediately before and
after the channel copy. With the inhibit active, the packed timestamps must be
equal. This check should report an error rather than silently accepting a
changed timestamp.

Accept the joint implementation when:

1. register address, bit definition, reset value, and readback match this
   document;
2. both trigger sources are blocked while inhibited;
3. an in-progress capture is never truncated;
4. timestamps remain stable during every protected copy;
5. all channels belonging to one waveform come from the same capture;
6. inhibit is released after successful and failed requests;
7. old firmware without the register is detected and rejected when protected
   readout is required;
8. skipped triggers at rates above server capacity are reported as intentional
   readout dead time, not as corruption;
9. the ramp validator reports no temporal discontinuities;
10. the channel-identity validator reports no complete swaps, temporary mixes,
    or unknown channel intervals.

## Coordinated delivery checklist

### Firmware repository

- [x] Implement `spy_readout_inhibit_reg` at `0x9400004C`.
- [x] Add the CDC synchronizer and combined-trigger gate.
- [x] Preserve completion of an in-progress capture by gating trigger
      admission rather than the BRAM write enable.
- [x] Update `Memory_Map.md` and `docs/modules/spy-buffer.md`.
- [x] Extend the STUFF and trigger-plane smoke tests.
- [ ] Add the capture integration test that observes BRAM/timestamp stability.
- [x] Record the first firmware implementation commit: `f0d48d6`.

### Server repository

- [x] Add `spyReadoutInhibit` at relative address `0x1400004C`.
- [x] Increase the register-dictionary test count from 388 to 389.
- [x] Add readback-based incompatible-firmware detection.
- [x] Refactor timestamp waiting and protected copying in
      `SpyBuffer::acquireFreshMappedData`.
- [x] Assert inhibit, wait 35 microseconds, and read the frozen timestamp.
- [x] Copy all requested channels under one global inhibit interval.
- [x] Compare timestamps before and after the protected copy.
- [x] Release inhibit before waiting for the next deduplicated timestamp.
- [x] Guarantee release with RAII on every exit path.
- [x] Use the same protected method from both normal and chunked dump APIs.
- [x] Add unit tests for register metadata, incompatible firmware, normal
      release, exception cleanup, and failed-release retry.

### Hardware verification

- [x] Add an AFE ramp continuity smoke test for normal and chunked APIs.
- [x] Run the AFE ramp smoke test on matching firmware/server hardware;
      37-channel provisional baseline passes and full 40-channel acceptance is
      blocked by three frontend lanes.
- [ ] Exercise both normal and chunked readout with one and 40 channels.
- [ ] Run the complete trigger-rate matrix with the 35 microsecond guard.
- [ ] Verify static physical-to-server channel mapping.
- [ ] Implement the normal-mode per-channel tag campaign.
- [ ] Verify zero complete channel swaps and zero temporary channel-mix
      intervals.
- [ ] Verify inhibit returns low after successful requests, client errors, and
      orderly server shutdown.
- [ ] Verify server startup clears inhibit after an ungraceful previous exit.

### Deployment

- [ ] Deploy a matching firmware/server pair.
- [ ] Confirm reset and startup readback before enabling trigger input.
- [ ] Run the joint hardware acceptance matrix.
- [ ] Record measured protected-copy time and resulting trigger dead time.
