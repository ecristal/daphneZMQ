# AFE input-delay eye sweep

## Purpose

The normal AFE alignment reports success after aligning only the frame-clock
pattern. It does not prove that all eight data lanes of an AFE deserialize the
synchronized count-up ramp correctly. The input-delay eye sweep is a separate
diagnostic that measures that missing condition without changing the
production `alignAFE` algorithm.

This distinction matters for the observed channels 3, 25, and 39. They belong
to three different AFEs, and their ramp discontinuities remain present with an
unplugged external-trigger cable and software-triggered acquisition. A
channel-by-tap map can distinguish a bad common delay choice from a lane that
has no usable region at any common delay.

## Diagnostic contract

The protobuf `AfeDelaySweepRequest` uses board AFE numbering (`0..4`) and
specifies an inclusive tap interval, step, sample count, waveform count, and a
delay-to-trigger settling time. `MT2_AFE_DELAY_SWEEP_REQ` is handled entirely
inside the server.

For each requested AFE the server:

1. reads and saves the original IDELAY, bitslip, `SYNC_PATTERN`,
   `TEST_PATTERN_MODES`, and global VTC-enable state;
2. disables VTC while loading manual IDELAY values;
3. enables the synchronized count-up ramp (`SYNC_PATTERN=1`,
   `TEST_PATTERN_MODES=7`);
4. sets a tap and waits the requested settling time before issuing any
   software trigger;
5. acquires the requested waveforms for all eight channels through the normal
   readout-inhibit and deduplication path;
6. counts every within-waveform transition whose 14-bit modular delta is not
   `+1`;
7. restores the original delay, AFE output mode, and VTC state before sending
   the response, including when acquisition or validation throws an error.

The server is single-threaded while the handler runs, so another control
request cannot interleave with the scan. A request is rejected if it would
exceed 100,000 software-triggered captures.

The response contains failure counts, rather than raw waveforms, for exactly
eight board channels at each tested tap. It also records the original delay and
bitslip so results can be compared with the setting selected by normal
alignment.

## Running a coarse scan

Rebuild the C++ and Python protobuf outputs and deploy the matching server
before running the client. Point `DAPHNE_PROTO_PYTHON_DIR` at the newly
generated Python bindings:

```bash
DAPHNE_PROTO_PYTHON_DIR="$PWD/build-petalinux/srcs/protobuf" \
python3 client/scan_afe_delay_eye.py \
  --ip 193.206.157.36 \
  --port 9876 \
  --route mezz/0 \
  --afes 0,3,4 \
  --first-tap 0 \
  --last-tap 511 \
  --tap-step 4 \
  --waveforms 8 \
  --samples 512 \
  --settle-us 10 \
  --timeout-ms 600000
```

The default pass criterion is strict: a tap passes a channel only if every
tested ramp transition is correct. `--max-error-rate` can be used for
exploration, but a nonzero value should not be used to qualify alignment.

The settling interval occurs *after* changing IDELAY and *before* the first
software trigger at that tap. This is important because the spybuffer contains
pre-trigger samples; sleeping only after a trigger would not make those samples
represent the new delay.

## Output

Every completed scan creates a timestamped directory below
`afe_delay_sweep_results/` containing:

- `summary.json`: request parameters, original alignment values, per-channel
  passing windows, common eight-channel windows, and recommended midpoints;
- `delay_sweep.csv`: exact failure count, transition count, error rate, and
  pass state for every AFE/channel/tap;
- `afeN_delay_eye.png`: a channel-by-tap heatmap using
  `log10(failures + 1)`, with the common passing window and its midpoint marked
  when one exists.

The console prints each channel's longest passing window separately and then
the intersection valid for all eight channels of the AFE.

## Interpretation

- A broad common window containing the original delay indicates that the
  shared IDELAY is viable. Persistent isolated channel errors then point away
  from the delay selector and toward lane deserialization, word assembly, or
  mapping.
- Clean per-channel windows with no common intersection indicate lane-to-lane
  skew larger than the shared timing margin. A single delay per AFE cannot
  satisfy that hardware state reliably.
- A channel with no clean tap while its seven neighbors have broad windows is
  evidence of a lane-specific problem rather than trigger rate or frame-clock
  alignment.
- A common window displaced from the original delay indicates that selecting
  the midpoint of the longest identical frame-clock region is not selecting
  the best data-eye point.
- Irregular errors across all eight channels and nearly every tap suggest
  checking bitslip or the ramp configuration before drawing an IDELAY
  conclusion.

After the coarse scan, repeat only the interesting AFE and tap interval with a
unit step and stronger statistics. For example:

```bash
DAPHNE_PROTO_PYTHON_DIR="$PWD/build-petalinux/srcs/protobuf" \
python3 client/scan_afe_delay_eye.py \
  --ip 193.206.157.36 --port 9876 --route mezz/0 \
  --afes 0 \
  --first-tap 120 --last-tap 240 --tap-step 1 \
  --waveforms 32 --samples 2048 \
  --settle-us 10 --timeout-ms 600000
```

The measured common midpoint is diagnostic only. This tool always restores the
original delay and does not apply a new production alignment value.
