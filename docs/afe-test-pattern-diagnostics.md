# AFE test-pattern diagnostics

## Purpose

The synchronized AFE ramp identifies channels whose sample sequence is not a
continuous 14-bit count, but it does not by itself distinguish a static bit
placement error from a word-to-word timing error. This diagnostic applies the
other AFE5808A test patterns and produces an explicit result for every
requested channel.

The principal use case is the investigation of channels 3 and 25. Their ramp
failures are concentrated around ADC bits D1 and D8 respectively. With the
current `bitslip=11` word assembly, those two bits are the lower and upper ends
of the same deserialized byte. The pattern matrix determines whether those bit
positions are already wrong for a constant serialized word, or only become
wrong when consecutive ADC words differ.

This is a frontend diagnostic. It always uses software triggers and the normal
protected spybuffer acquisition. It does not qualify external-trigger rate or
compare the normal and chunked readout APIs; those remain covered by the
readout-inhibit campaign.

Run it with exclusive control of the target DAPHNE. Another client changing AFE
registers between pattern acquisitions would invalidate the expected-versus-
received comparison and could also defeat exact state restoration.

## Applied patterns and exact expectations

The test uses 14-bit ADC codes (`D13..D0`) and applies 33 cases in this order:

| Test | AFE `TEST_PATTERN_MODES` | Expected server samples | Diagnostic role |
| --- | ---: | --- | --- |
| zeros | `6` (`110`) | `0x0000` | Detect bits stuck high |
| ones | `4` (`100`) | `0x3FFF` | Detect bits stuck low |
| deskew | `2` (`010`) | `0x1555` (`01010101010101`) | Check alternating static bit placement |
| sync word | `1` (`001`) | `0x3F80` (`11111110000000`) | Check a static transition inside the word |
| walking one D0..D13 | `3` (`011`) | exactly `1 << bit` | Map each input bit to its observed output bit |
| walking zero D0..D13 | `3` (`011`) | exactly `0x3FFF ^ (1 << bit)` | Confirm missing, stuck, duplicated, or inverted bits |
| toggle | `5` (`101`) | alternating `0x0000`, `0x3FFF` | Exercise every word-to-word boundary |

For `toggle`, either polarity may be the first sample. Every sample must be one
of the two complete words and every adjacent pair within a waveform must
change polarity. A value such as `0x0100` is reported separately as a hybrid
word; two equal adjacent valid words are reported as a missing transition.

The count-up ramp (`mode=7`) is intentionally not repeated here. It remains in
`test_spybuffer_readout_inhibit.py`; the pattern matrix is the complementary
diagnostic needed to interpret a ramp failure.

## Hardware state and safety

Only AFEs containing a requested channel are modified. Before the first
pattern, the client reads and saves the complete 16-bit values of AFE registers
2, 5, and 10, containing `TEST_PATTERN_MODES`, `CUSTOM_PATTERN`, and
`SYNC_PATTERN`. It enables synchronized patterns, runs the matrix, and restores
the three original register values in a `finally` cleanup path. Register 2 is
restored last so the original output mode is the final externally visible
state.

The restoration also runs after a normal exception or `Ctrl-C`. An
unrecoverable process or machine termination such as `SIGKILL` cannot execute
client-side cleanup; in that case restore the normal AFE configuration before
resuming data taking.

## Running the diagnostic

Rebuild the Python protobuf bindings and point the client to them. For the
first focused comparison, test all lanes of the two AFEs containing channels 3
and 25:

```bash
DAPHNE_PROTO_PYTHON_DIR="$PWD/build-petalinux/srcs/protobuf" \
python3 client/test_afe_pattern_matrix.py \
  --ip 193.206.157.36 \
  --port 9876 \
  --route mezz/0 \
  --channels 0-7,24-31 \
  --waveforms 16 \
  --samples 2048 \
  --timeout-ms 600000
```

The default quick campaign uses all 40 channels, 8 waveforms, and 256 samples
per pattern:

```bash
DAPHNE_PROTO_PYTHON_DIR="$PWD/build-petalinux/srcs/protobuf" \
python3 client/test_afe_pattern_matrix.py \
  --ip 193.206.157.36 --port 9876 --route mezz/0
```

Each pattern is configured before its acquisition and the client waits
`--settle-ms` after the SPI writes. The default is 10 ms, far longer than the
AFE pattern update latency and long enough to replace the pre-trigger
spybuffer history with the new pattern.

## Console result

Each pattern line contains:

- the exact expected word or toggle behavior;
- the total number of checks and failures;
- the failing channel set;
- for a limited number of failing channels, the dominant received code,
  wrong-code count, bad-transition count, and affected bit positions.

The final section reports one classification per failing channel and one
compact range containing every passing channel. A channel passes only if it
has zero errors in all 33 patterns and every acquired waveform.

## Channel classifications

| Classification | Measured result | Interpretation and next action |
| --- | --- | --- |
| `PASS` | All fixed, custom, and toggle checks pass | Static bit placement and inter-word timing are correct for the tested conditions |
| `STATIC_BIT_PATH_FAILURE` | At least one custom walking pattern is wrong; toggle passes | Constant words are already deserialized incorrectly; inspect lane bitslip, bit order, padding, and physical/static serial path |
| `TEMPORAL_WORD_BOUNDARY_FAILURE` | All custom walking patterns pass; toggle fails | Bit positions are correct for constant words, but different consecutive words are mixed; inspect the `clk125` to 62.5-MHz word assembly boundary |
| `STATIC_AND_TEMPORAL_FAILURE` | Custom patterns and toggle both fail | More than one fault may exist, or a static placement fault also corrupts transitions; use walking-bit mapping and toggle hybrid codes together |
| `BUILTIN_PATTERN_MISMATCH` | Custom walking patterns and toggle pass, but a built-in fixed pattern fails | The serialized bit path is viable; verify AFE mode selection, documented built-in code, output format, and SPI configuration |

For a failing walking-one case, the response is rendered explicitly. Examples:

- `D1->missing`: stimulus D1 never appears in the dominant received word;
- `D8->D0`: stimulus D8 appears at output bit D0;
- `D3->D3+D4`: one source bit appears in multiple output positions;
- `D5->D5 (dominant 4000/4096)`: the expected mapping dominates but is
  intermittent rather than stable.

`affected_bits` is the union of every static expected-versus-received XOR. The
CSV files retain separate counts for false-positive bits (unexpected ones) and
false-negative bits (missing ones).

## Output files

Every invocation creates a timestamped directory below
`afe_pattern_test_results/`, including successful runs:

- `summary.json`: complete request, original register state, timestamps,
  per-pattern results, channel classifications, examples, and restoration
  status;
- `pattern_results.csv`: one row per pattern and channel with the expected
  word, dominant response, exact error counts, affected bits, and most common
  received codes;
- `failure_examples.csv`: representative waveform/sample positions with the
  previous, received, and expected code;
- `channel_diagnosis.csv`: the final per-channel classification and its
  interpretation.

A run is reported as `ERROR`, rather than `PASS` or `FAIL`, if the matrix is
incomplete, acquisition/configuration throws, or any register fails to
restore. Deep details remain available in the output directory even for a
partial run.

## Decision for channels 3 and 25

The most discriminating outcomes are:

1. If both channels pass every walking pattern but fail `toggle`, prioritize a
   firmware experiment that stabilizes the byte pipeline before the 16-bit
   word is assembled. This supports the current word-boundary tearing
   hypothesis.
2. If channel 3 consistently reports `D1->missing` or channel 25 maps D8 to a
   different output bit for constant custom words, investigate per-lane
   bitslip/serialization and inspect the two raw padding bits before changing
   the clock-domain assembly.
3. If the same pattern fails across all eight channels of one AFE, first verify
   the AFE pattern configuration and common alignment rather than treating it
   as an isolated lane defect.
4. If only the built-in patterns fail while all custom and toggle cases pass,
   do not infer an FPGA data-path fault until the AFE mode and expected built-in
   code have been independently confirmed.

## Reference result: 2026-08-03

The focused matrix was completed against `tcp://193.206.157.36:9876`, route
`mezz/0`, for channels `0-7,24-31`. Each of the 33 patterns acquired 16
waveforms of 2048 samples, giving 32768 observed values per channel for every
fixed or custom pattern. All patterns completed and registers 2, 5, and 10 were
restored without error.

The raw run result was `FAIL` for all 16 requested channels, but that headline
must not be interpreted as 16 independent lane failures. Fourteen channels
passed every custom walking pattern and the temporal toggle pattern. Their only
failure was the built-in sync word:

```text
AFE5808A documented sync word : 0x3F80 (11111110000000)
Observed on all otherwise-good lanes: 0x3FC0
Common difference             : D6
```

The expected `0x3F80` agrees with the
[AFE5808A data sheet](https://www.ti.com/lit/ds/symlink/afe5808a.pdf). The
uniform `0x3FC0` response is therefore tracked as a separate
mode/configuration discrepancy; it must not be silently adopted as a new
expected value, nor counted as evidence that all 16 serial lanes are
defective.

After separating that common discrepancy, the diagnostic result is 14 clean
lanes and two lanes with reproducible data-path failures:

| Channel | Constant-pattern response | Toggle response | Interpretation |
| ---: | --- | --- | --- |
| 3 | `D1` is predominantly missing; driving `D9` also produces `D1` | zero half-word is predominantly `0x0002`, while the ones half-word remains `0x3FFF` | `D1` is consistent with information from `D9` of an adjacent serialized word |
| 25 | `D0` produces `D0+D8`; `D8` is missing; `D4` is missing; `D12` produces `D12+D4` | alternates deterministically between `0x0010` and `0x3FEF` instead of complete zero/one words | `D8` follows current-word `D0`; `D4` is consistent with `D12` of an adjacent word |

For channel 3, `walking-one D1` returned `0x0000` in 27845 of 32768
observations, while `walking-one D9` returned `0x0202` in 32767 of 32768.
The toggle corruption occurred in 16204 of the 16384 expected zero samples.

For channel 25, the D0/D8 and D4/D12 substitutions were deterministic or
within a few samples of deterministic across 32768 observations. Every toggle
sample was hybrid: exactly 16384 observations of `0x0010` and 16384 of
`0x3FEF`.

The same substitutions explain the earlier synchronized-ramp histograms:

- replacing D1 produces the channel-3 `+3` and `-1` discontinuities;
- making D8 follow D0 produces the channel-25 `+257` and `-255`
  discontinuities;
- the additional D4 contribution accounts for variants displaced by 16,
  including `-271` and `-239`.

They also reproduce the measured sync codes when the common `0x3FC0` response
is used as the unaffected-lane reference:

```text
channel 3 : 0x3FC0 + D1      = 0x3FC2
channel 25: 0x3FC0 - D8 + D4 = 0x3ED0
```

Channel 39 was not part of this focused run and remains to be characterized by
the same matrix.

The AFE applies the same test pattern to all of its channels. Consequently,
this test diagnoses bit placement and word-boundary integrity, but cannot by
itself exclude mixing between two physical channels carrying identical test
words. Channel identity requires distinct simultaneous stimuli, for example
independent analog inputs, or at least different patterns per AFE to detect
cross-AFE mixing.

## Gateware interpretation

The lane receiver is generated from the same `febit3` RTL for every channel.
This rules out a handwritten ch3/ch25 special case, but it does not rule out a
common timing defect whose manifestation depends on each placed-and-routed
instance.

In `febit3.vhd`, `q_reg`, `q2_reg`, and `q3_reg` are updated by `clk125`.
`dout_reg` is assembled in a separate process driven by the 62.5-MHz word
clock. For bitslip 11, that process concatenates:

```text
q_reg(4 downto 0) & q2_reg(7 downto 0) & q3_reg(7 downto 5)
```

The design assumes frequency-locked clocks with aligned rising edges, so the
word-clock process can sample these registers at the same nominal instant at
which the `clk125` process advances them. Without an explicit safe transfer,
clock skew, clock-to-Q, routing delay, setup, and hold determine whether an
individual destination bit observes the old or new byte generation.

This is a structural clock-boundary risk exposed by placement, not merely a
placement optimization problem. Identical RTL instances have different pins,
routes, and timing margins. A fixed bitstream may therefore fail consistently
on particular lanes, while a new implementation seed, another board, or
process/voltage/temperature variation may expose other lanes. Constraining or
locking placement around the currently failing channels would be a fragile
mitigation rather than a correction.

The measured eight-bit relationships are consistent with the ISERDES byte
width and with mixing adjacent generations in the `q` history. This remains a
firmware hypothesis until an ILA capture or an equivalent internal observation
shows the byte epochs on both sides of the boundary.

## Required firmware response if the hypothesis is confirmed

The correction must establish the invariant that every bit of an emitted
16-bit word comes from one stable snapshot of the serial history.

The preferred architecture is:

```text
ISERDES Q @ clk125
    -> 24/32-bit registered serial history @ clk125
    -> bitslip selection and complete 16-bit word register @ clk125
    -> word_valid
    -> clock enable in clk125, or a dual-clock FIFO
    -> downstream word-clock logic
```

Using a `clk125` clock enable for the 62.5-Msample/s cadence removes the data
clock crossing if the downstream design can accept it. If the downstream must
remain in the word-clock domain, only complete registered words should cross
through a dual-clock FIFO. The current approach of combining live fragments
under the assumption of coincident clock edges must not remain the production
interface.

An IDELAY or bitslip change must invalidate capture, clear the byte history and
any FIFO, allow the new setting to settle, retrain, and only then reassert
`word_valid`. This prevents the reconfiguration boundary itself from emitting
a hybrid word.

IDELAY and bitslip are currently common to the lanes of an AFE. After fixing
the clock boundary, repeat the per-channel eye measurements. If the clean
windows of the lanes do not overlap, promote IDELAY and, if required, bitslip
to per-lane controls. Do not make that register-map expansion solely from the
current results, because the suspected boundary defect may be distorting the
measured eyes.

Firmware sign-off requires all of the following:

1. `report_clock_interaction` and `report_cdc` show no uncontrolled version of
   the old `clk125` to word-clock transfer, and setup/hold timing passes at all
   implementation corners with correctly declared clocks and exceptions.
2. RTL verification proves that each valid output is a contiguous 16-bit
   window from one registered history epoch, including reset and runtime
   bitslip/IDELAY changes.
3. Hardware walking-one, walking-zero, toggle, and ramp tests pass with zero
   hybrid words on all 40 channels over several million samples.
4. The result remains clean across multiple implementation seeds, resets,
   power cycles, and representative temperature/voltage conditions.
5. The focused matrix is rerun for channels 3, 25, and 39, followed by the
   complete readout-inhibit campaign using normal and chunked acquisition.

ILA probes should cover ISERDES `Q`, the registered byte history, the assembled
word, `word_valid` or FIFO write/read controls, and final `dout`. Because adding
an ILA can itself perturb placement, retain the implementation reports and
compare both debug and non-debug builds before declaring the placement
sensitivity resolved.
