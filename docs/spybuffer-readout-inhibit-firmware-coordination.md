# Spybuffer Readout Inhibit: Firmware Coordination Contract

## Status

This document defines the proposed contract between `daphneZMQ` and
`daphne-firmware` for protecting spybuffer data while the server copies a
captured waveform.

The contract is not implemented in the current firmware. The server register
map was synchronized with the existing firmware in `daphneZMQ` commit
`99ee1a1`, and currently ends the STUFF register block at physical address
`0x94000048`.

Do not deploy server-side inhibit writes until the firmware implementation and
the memory map described here are available in the loaded bitstream.

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

The first hardware-triggered waveform retains the existing deduplication
behavior and may use the snapshot already present when the request starts.
Deduplication is applied between subsequent waveforms.

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

Run the existing deduplication client together with a waveform suited to
detecting discontinuities, such as a ramp, counter pattern, or phase-locked
sine wave.

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
   readout dead time, not as corruption.

## Coordinated delivery checklist

### Firmware repository

- [ ] Implement `spy_readout_inhibit_reg` at `0x9400004C`.
- [ ] Add the CDC synchronizer and combined-trigger gate.
- [ ] Preserve completion of an in-progress capture.
- [ ] Update `Memory_Map.md`.
- [ ] Extend STUFF, trigger-plane, and capture integration tests.
- [ ] Record the first firmware version/commit that implements the contract.

### Server repository

- [ ] Add `spyReadoutInhibit` at relative address `0x1400004C`.
- [ ] Increase the register-dictionary test count from 388 to 389.
- [ ] Add readback-based incompatible-firmware detection.
- [ ] Refactor timestamp waiting and protected copying in
      `SpyBuffer::acquireFreshMappedData`.
- [ ] Assert inhibit, wait for capture completion, and read the frozen timestamp.
- [ ] Copy all requested channels under one global inhibit interval.
- [ ] Release inhibit before waiting for the next deduplicated timestamp.
- [ ] Guarantee release with RAII on every exit path.
- [ ] Verify both normal and chunked dump APIs.

### Deployment

- [ ] Deploy a matching firmware/server pair.
- [ ] Confirm reset and startup readback before enabling trigger input.
- [ ] Run the joint hardware acceptance matrix.
- [ ] Record measured protected-copy time and resulting trigger dead time.
