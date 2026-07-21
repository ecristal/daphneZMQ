# DAPHNE AFE alignment failure investigation and fix

This document records the 2026-07-21 investigation and fix for the DAPHNE
AFE alignment false-failure condition.

See the current branch history for the implementation commits:

- `e920847` Fix AFE alignment false failure criterion
- `3fcc5a8` Wait for AFE alignment diagnostic snapshot
- `fd5df2a` Restore delay VTC after alignment errors
- `0e14f77` Add detailed AFE alignment diagnostics
- `90ed100` Fix AFE diagnostic read indentation

## Executive summary

The DAPHNE AFE alignment failure was traced to a server-side false-failure
condition. The server compares 32-bit integers, so a logged `0xFF00FF` is
numerically equal to the expected `0x00FF00FF`. This was not a leading-zero or
string-comparison bug.

Before the fix, the server made an extra post-selection spy-buffer read
immediately after triggering the FPGA snapshot and included it in the pass/fail
decision. Unlike the delay scan and later verification reads, it did not wait
for the snapshot to latch. It could therefore contain stale data even when the
bitslip scan and all four verification reads were correct.

The pass rule is now deliberately strict but reliable:

```text
bitslip scan found 0x00FF00FF
AND all four settled verification reads equal 0x00FF00FF
```

The post-selection value remains available for diagnosis, but cannot affect the
alignment result. A target test after deployment passed both embedded
ConfigureFE alignment and the following explicit AlignAFE operation.

## Reference reproduction

```bash
python client/configure_fe_min_v2.py \
  -ip 193.206.157.36 -port 9876 --route mezz/0 \
  -vgain 1700 -ch_offset 2275 -lpf_cutoff 10 \
  -pga_clamp_level '-2 dBFS' -pga_gain_control '24 dB' \
  -lna_gain_control '12 dB' -lna_input_clamp '1.15 Vpp' \
  --full -align_afes --adc_resolution 0 \
  --timeout 30000 --cfg-timeout-ms 30000 --biasctrl-dac 1300
```

With `-align_afes`, the client exercises both paths:

```text
MT2_CONFIGURE_FE_REQ -> configureDaphne(...) -> alignAFE(...)
MT2_ALIGN_AFE_REQ -> alignAFE(...)
```

ConfigureFE automatically invokes alignment unless
`DAPHNE_SKIP_ALIGN_AFTER_CONFIGURE` is set. Both operations call the same
`alignAFE(...)` routine, so the original common failure was expected.

## Code path inspected

### RPC handlers

`srcs/server_controller/handlers.cpp` implements `alignAFE(...)`.

- It resets delay control and SERDES, disables delay VTC, waits for
  `DELAYCTRL_READY`, and processes AFE blocks 0 through 4.
- The ConfigureFE handler calls it after `configureDaphne(...)` when automatic
  alignment is enabled.
- The explicit `MT2_ALIGN_AFE_REQ` handler calls it directly.
- It records the selected delay and bitslip values in the response.

### Delay, bitslip, and snapshot reads

`srcs/Daphne.cpp` provides the underlying scans.

- `Daphne::scanGeneric(...)` applies one candidate, triggers the frontend
  snapshot, waits 1 ms, then reads the frame-clock word.
- `Daphne::setBestDelay(...)` scans 512 delay taps and selects the midpoint of
  the longest run of identical sampled words.
- `Daphne::setBestBitslip(...)` scans 16 bitslip positions and finds the first
  value whose sampled 32-bit word equals `0x00FF00FFu`.

`SpyBuffer::getFrameClock(...)` in `srcs/SpyBuffer.cpp` returns a full
`uint32_t`. The target comparison is numeric; log formatting simply omits
leading zeroes.

## Root cause

The old result check was effectively:

```cpp
if (!matched || aligned_word != kExpectedFclkWord || !verification_ok) {
  // report this AFE as failed
}
```

`matched` was true when the bitslip scan found the expected word.
`verification_ok` required all four post-selection reads, each after a 1 ms
delay, to match. `aligned_word` came from `setBestBitslip(...)`, which had set
the selected bitslip, triggered the spy buffer, and read it immediately.

That immediate value was timing-sensitive and non-authoritative. It could
reflect the preceding snapshot while the later, settled verification reads
were all correct. This directly explains failure logs containing a valid
bitslip choice and four valid `VERIFY_SCAN` words, and it is consistent with
the failed AFE set changing between attempts.

The unsafe criterion became significant in commit `5b6dadb` ("Tighten AFE
alignment acceptance checks"). The post-selection read already existed, but
that change made it a hard success criterion.

## Fix commits

The changes were intentionally split into small commits.

| Commit | Change | Effect |
| --- | --- | --- |
| `e920847` | Remove `aligned_word` from the acceptance test. | Eliminates the false-failure gate while retaining scan and verification checks. |
| `3fcc5a8` | Wait 1 ms before the post-selection diagnostic read. | Makes the diagnostic use the same snapshot cadence as scan and verification. |
| `fd5df2a` | Restore delay VTC on alignment exceptions. | Prevents an error after VTC disable from leaving VTC disabled. |
| `0e14f77` | Add detailed per-AFE diagnostics. | Identifies bitslip misses and failed verification-sample indices. |
| `90ed100` | Repair literal `\\t` text in `Daphne.cpp`. | Fixes the target-side C++ compilation error introduced by the timing edit. |

### Current acceptance rule

The current condition is equivalent to:

```cpp
if (!matched || !verification_ok) {
  // report this AFE as failed
}
```

The post-selection word is diagnostic only. It cannot override a successful
bitslip scan and four successful settled verification reads.

### Current diagnostic output

Every AFE now emits a status line such as:

```text
ALIGNMENT_STATUS: bitslip_scan=MATCH,
post_selection=0xFF00FF (MATCH, diagnostic only), verify=PASS
```

Failures identify their phase and the failed verification samples, for example:

```text
AFE_3 alignment failed: VERIFY_SCAN mismatch at samples: 1 3.
```

This keeps real alignment failures visible while making a stale diagnostic read
non-blocking.

## Local validation

- `git diff --check` passed for each commit.
- The portable Windows CMake build with `DAPHNE_BUILD_SERVER=OFF` passed its
  `hdmezz_driver_unit` target (`1/1` tests passed).
- Full server configuration could not run on that Windows development host
  because Protobuf/protoc was unavailable. The target PetaLinux build is the
  relevant compilation validation for the edited server source.

## Target validation: successful run on 2026-07-21

The reference command was run against `193.206.157.36:9876`, route `mezz/0`.
The supplied client log showed:

- `ConfigureResponse.success : True` and embedded `[ALIGN_AFE] AFEs aligned.`
- explicit `[ALIGN_RESULT] success : True`.
- AFE0 through AFE4 all reported `bitslip_scan=MATCH` and `verify=PASS`.
- Every displayed verification sample was `0xFF00FF`, numerically equal to
  `0x00FF00FF`.

The two independent alignment scans selected:

| AFE | ConfigureFE delay / bitslip | Explicit AlignAFE delay / bitslip |
| --- | --- | --- |
| 0 | 290 / 5 | 290 / 5 |
| 1 | 128 / 5 | 129 / 5 |
| 2 | 386 / 5 | 385 / 5 |
| 3 | 382 / 6 | 383 / 6 |
| 4 | 351 / 6 | 349 / 6 |

Small midpoint changes between independent scans are expected. The important
result is that every AFE found the expected bitslip position and passed all
four settled verification reads.

The response timestamp decoded by the client as a 1970 date is outside the
alignment issue. Track it separately only if accurate server wall-clock time is
required.

## Follow-up rules

- A future `bitslip_scan=MISS` indicates that the scan did not observe the
  expected training pattern.
- A future `verify=FAIL` indicates genuine unstable or incorrect settled
  samples; inspect the reported sample indices.
- In either case, investigate firmware/hardware: delay-line programming,
  SERDES/bitslip behavior, training-pattern generation, ADC output format and
  bit order, clock/endpoint state, and capture-path clock-domain crossings.

QA/QC must continue to consider failed ConfigureFE or AlignAFE responses as not
ready for acquisition. This fix removes a false negative; it does not relax
the actual alignment-stability requirement.
